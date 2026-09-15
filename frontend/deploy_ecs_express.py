"""Deploys the Streamlit demo UI to Amazon ECS Express Mode (task #28, ADR-0003).

★ 왜 App Runner가 아니라 ECS Express Mode인가 ★
`frontend/deploy_apprunner.py`로 App Runner를 시도한 결과, 이 계정(430013477501)
에서 모든 App Runner API 호출이 리전과 무관하게 다음 오류로 실패했다:

    SubscriptionRequiredException: The AWS Access Key Id needs a subscription
    for the service

`AWSAppRunnerFullAccess`를 IAM 사용자에 추가한 뒤에도 동일하게 실패해 IAM 권한
문제가 아님을 확인했다. AWS 공식 문서
(https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html)
에 따르면 App Runner는 신규 고객에게 닫혀 있는 계정 레벨 제한이며, 콘솔 방문이나
IAM 정책 추가로는 풀리지 않는다. Bedrock Agents Classic(ADR-0003 본문 참고)에
이어 이번 대회 기간 중 두 번째로 발견한 동일 패턴이다.

Amazon ECS Express Mode는 re:Invent 2025에서 발표된 App Runner의 공식 후속
서비스다. `frontend/deploy_apprunner.py`가 이미 ECR에 push해 둔 동일한 컨테이너
이미지(mfg-investigation-frontend:latest)를 그대로 재사용한다 -- 이미지 자체는
배포 플랫폼에 종속적이지 않다는 걸 보여준다.

Run: python frontend/deploy_ecs_express.py
"""

from __future__ import annotations

import json
import subprocess
import time

import boto3

REGION = "us-east-1"
ECR_REPO_NAME = "mfg-investigation-frontend"
IMAGE_TAG = "latest"
SERVICE_NAME = "mfg-investigation-frontend"
EXEC_ROLE_NAME = "ecsTaskExecutionRole"
INFRA_ROLE_NAME = "ecsInfrastructureRoleForExpressServices"
# The Lambda+API Gateway backend deployed by backend/deploy_lambda_api.py.
BACKEND_URL = "https://dwn13wrel9.execute-api.us-east-1.amazonaws.com"

sts = boto3.client("sts", region_name=REGION)
ACCOUNT_ID = sts.get_caller_identity()["Account"]
ECR_URI = f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/{ECR_REPO_NAME}:{IMAGE_TAG}"


def ensure_iam_roles() -> tuple[str, str]:
    iam = boto3.client("iam")
    exec_role_arn = f"arn:aws:iam::{ACCOUNT_ID}:role/{EXEC_ROLE_NAME}"
    infra_role_arn = f"arn:aws:iam::{ACCOUNT_ID}:role/{INFRA_ROLE_NAME}"

    exec_trust = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"}, "Action": "sts:AssumeRole"}
        ],
    }
    infra_trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowAccessInfrastructureForECSExpressServices",
                "Effect": "Allow",
                "Principal": {"Service": "ecs.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    for name, trust, policy_arn in [
        (
            EXEC_ROLE_NAME,
            exec_trust,
            "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
        ),
        (
            INFRA_ROLE_NAME,
            infra_trust,
            "arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices",
        ),
    ]:
        try:
            iam.create_role(RoleName=name, AssumeRolePolicyDocument=json.dumps(trust))
            print(f"created role {name}")
        except iam.exceptions.EntityAlreadyExistsException:
            print(f"role {name} already exists")
        iam.attach_role_policy(RoleName=name, PolicyArn=policy_arn)

    print("waiting 30s for IAM role propagation...")
    time.sleep(30)
    return exec_role_arn, infra_role_arn


def push_image() -> None:
    """Image was already built by frontend/deploy_apprunner.py; re-push in
    case the ECR repo/tag needs refreshing."""
    login_password = subprocess.run(
        ["aws", "ecr", "get-login-password", "--region", REGION],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin",
         f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com"],
        input=login_password,
        text=True,
        check=True,
    )
    subprocess.run(["docker", "push", ECR_URI], check=True)
    print(f"pushed {ECR_URI}")


def create_express_service(exec_role_arn: str, infra_role_arn: str) -> dict:
    primary_container = {
        "image": ECR_URI,
        "containerPort": 8080,
        "environment": [{"name": "BACKEND_URL", "value": BACKEND_URL}],
    }
    client = boto3.client("ecs", region_name=REGION)
    response = client.create_express_gateway_service(
        serviceName=SERVICE_NAME,
        primaryContainer=primary_container,
        executionRoleArn=exec_role_arn,
        infrastructureRoleArn=infra_role_arn,
        healthCheckPath="/_stcore/health",
    )
    print(json.dumps(response["service"], indent=2, default=str))
    return response["service"]


def wait_rollout_complete(timeout_s: int = 300) -> None:
    client = boto3.client("ecs", region_name=REGION)
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        response = client.describe_services(cluster="default", services=[SERVICE_NAME])
        service = response["services"][0]
        deployment = service["deployments"][0]
        rollout = deployment.get("rolloutState", "UNKNOWN")
        running = service.get("runningCount", 0)
        print(f"rolloutState={rollout} runningCount={running}")
        if rollout == "COMPLETED" and running >= 1:
            return
        if rollout == "FAILED":
            print(json.dumps(deployment, indent=2, default=str))
            raise SystemExit("ECS Express deployment failed")
        time.sleep(10)
    raise SystemExit("Timed out waiting for ECS Express service rollout")


def get_endpoint() -> str:
    client = boto3.client("ecs", region_name=REGION)
    response = client.describe_services(cluster="default", services=[SERVICE_NAME])
    deployment = response["services"][0]["deployments"][0]
    return deployment["ingressPaths"][0]["endpoint"]


if __name__ == "__main__":
    exec_role_arn, infra_role_arn = ensure_iam_roles()
    push_image()
    create_express_service(exec_role_arn, infra_role_arn)
    wait_rollout_complete()
    print(f"endpoint={get_endpoint()}")
