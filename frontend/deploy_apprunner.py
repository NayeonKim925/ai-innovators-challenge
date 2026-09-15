"""Deploys the Streamlit demo UI to AWS App Runner (task #28).

App Runner (not Lambda) is used for the frontend because Streamlit is a
long-running stateful server process (WebSocket connections for live
widgets), which does not fit the Lambda request/response model that the
backend API uses. This matches the user's instruction: backend via
Lambda+API Gateway, frontend via App Runner.

Run: python frontend/deploy_apprunner.py
"""

from __future__ import annotations

import json
import subprocess
import time

import boto3

REGION = "us-east-1"
ECR_REPO_NAME = "mfg-investigation-frontend"
IMAGE_TAG = "latest"
LOCAL_IMAGE = "mfg-investigation-frontend:latest"
SERVICE_NAME = "mfg-investigation-frontend"
# The Lambda+API Gateway backend deployed by backend/deploy_lambda_api.py.
BACKEND_URL = "https://dwn13wrel9.execute-api.us-east-1.amazonaws.com"

sts = boto3.client("sts", region_name=REGION)
ACCOUNT_ID = sts.get_caller_identity()["Account"]
ECR_URI = f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/{ECR_REPO_NAME}:{IMAGE_TAG}"


def ensure_ecr_repo() -> None:
    ecr = boto3.client("ecr", region_name=REGION)
    try:
        ecr.describe_repositories(repositoryNames=[ECR_REPO_NAME])
        print(f"ECR repo {ECR_REPO_NAME} already exists")
    except ecr.exceptions.RepositoryNotFoundException:
        ecr.create_repository(repositoryName=ECR_REPO_NAME)
        print(f"created ECR repo {ECR_REPO_NAME}")


def push_image() -> None:
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
    subprocess.run(["docker", "tag", LOCAL_IMAGE, ECR_URI], check=True)
    subprocess.run(["docker", "push", ECR_URI], check=True)
    print(f"pushed {ECR_URI}")


def ensure_access_role() -> str:
    """App Runner needs an ECR access role separate from the instance role."""
    iam = boto3.client("iam")
    role_name = "AppRunnerECRAccessRole-mfg-investigation-frontend"
    role_arn = f"arn:aws:iam::{ACCOUNT_ID}:role/{role_name}"
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "build.apprunner.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    try:
        iam.create_role(RoleName=role_name, AssumeRolePolicyDocument=json.dumps(trust_policy))
        print(f"created role {role_name}")
        time.sleep(10)
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"role {role_name} already exists")
    iam.attach_role_policy(
        RoleName=role_name,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess",
    )
    return role_arn


def ensure_service(access_role_arn: str) -> dict:
    client = boto3.client("apprunner", region_name=REGION)
    services = client.list_services()
    for svc in services["ServiceSummaryList"]:
        if svc["ServiceName"] == SERVICE_NAME:
            print(f"service already exists: {svc['ServiceArn']}")
            return svc

    response = client.create_service(
        ServiceName=SERVICE_NAME,
        SourceConfiguration={
            "ImageRepository": {
                "ImageIdentifier": ECR_URI,
                "ImageRepositoryType": "ECR",
                "ImageConfiguration": {
                    "Port": "8080",
                    "RuntimeEnvironmentVariables": {"BACKEND_URL": BACKEND_URL},
                },
            },
            "AuthenticationConfiguration": {"AccessRoleArn": access_role_arn},
            "AutoDeploymentsEnabled": False,
        },
        InstanceConfiguration={"Cpu": "0.25 vCPU", "Memory": "0.5 GB"},
        HealthCheckConfiguration={"Protocol": "TCP"},
    )
    print(json.dumps(response["Service"], indent=2, default=str))
    return response["Service"]


def wait_service_running(service_arn: str, timeout_s: int = 420) -> str:
    client = boto3.client("apprunner", region_name=REGION)
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        response = client.describe_service(ServiceArn=service_arn)
        status = response["Service"]["Status"]
        print(f"status={status}")
        if status == "RUNNING":
            return response["Service"]["ServiceUrl"]
        if status in ("CREATE_FAILED", "DELETE_FAILED"):
            print(json.dumps(response["Service"], indent=2, default=str))
            raise SystemExit(f"Service failed with status={status}")
        time.sleep(15)
    raise SystemExit("Timed out waiting for App Runner service to become RUNNING")


if __name__ == "__main__":
    ensure_ecr_repo()
    push_image()
    access_role_arn = ensure_access_role()
    service = ensure_service(access_role_arn)
    service_arn = service["ServiceArn"]
    print(f"service_arn={service_arn}")
    url = wait_service_running(service_arn)
    print(f"service_url=https://{url}")
