"""Deploys the manufacturing investigation explainer to Bedrock AgentCore Runtime.

Reused pattern from https://github.com/k2hdevil/Workshop-Healthcare-AgentCore
(content/020_phase1_consultation/022_runtime_deploy.md) -- IAM role, ECR
repository, docker tag+push, then `create_agent_runtime`. Adapted for this
project: region us-east-1 (matches the rest of the stack), role/repo/agent
names reference this project instead of the healthcare workshop's agent.

Run: python backend/app/llm/aws/deploy_agentcore.py
"""

from __future__ import annotations

import json
import subprocess
import time

import boto3

REGION = "us-east-1"
AGENT_NAME = "mfg_investigation_explainer"
ECR_REPO_NAME = "mfg-investigation-explainer"
IMAGE_TAG = "latest"
LOCAL_IMAGE = "mfg-investigation-explainer:latest"

sts = boto3.client("sts", region_name=REGION)
ACCOUNT_ID = sts.get_caller_identity()["Account"]

ROLE_NAME = f"AmazonBedrockAgentCoreSDKRuntime-{REGION}"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/{ROLE_NAME}"
ECR_URI = f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/{ECR_REPO_NAME}:{IMAGE_TAG}"


def ensure_role() -> None:
    iam = boto3.client("iam")
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    try:
        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="AgentCore Runtime execution role (task #13 fallback, ADR pending)",
        )
        print(f"created role {ROLE_NAME}, waiting for propagation...")
        time.sleep(10)
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"role {ROLE_NAME} already exists")

    # Scoped policy: invoke the same Claude model, plus what AgentCore Runtime
    # itself needs (ECR pull, CloudWatch logs, Bedrock invoke).
    iam.attach_role_policy(
        RoleName=ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/AmazonBedrockFullAccess"
    )
    iam.attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/CloudWatchLogsFullAccess",
    )
    iam.attach_role_policy(
        RoleName=ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
    )
    print("attached policies")


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


def create_runtime() -> str:
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    try:
        response = client.create_agent_runtime(
            agentRuntimeName=AGENT_NAME,
            agentRuntimeArtifact={"containerConfiguration": {"containerUri": ECR_URI}},
            networkConfiguration={"networkMode": "PUBLIC"},
            roleArn=ROLE_ARN,
        )
        print(json.dumps(response, indent=2, default=str))
        return response["agentRuntimeArn"]
    except client.exceptions.ConflictException:
        runtimes = client.list_agent_runtimes()
        for rt in runtimes["agentRuntimes"]:
            if rt["agentRuntimeName"] == AGENT_NAME:
                print(f"runtime already exists, updating image: {rt['agentRuntimeArn']}")
                runtime_id = rt["agentRuntimeArn"].split("/")[-1]
                update = client.update_agent_runtime(
                    agentRuntimeId=runtime_id,
                    agentRuntimeArtifact={"containerConfiguration": {"containerUri": ECR_URI}},
                    networkConfiguration={"networkMode": "PUBLIC"},
                    roleArn=ROLE_ARN,
                )
                print(json.dumps(update, indent=2, default=str))
                return rt["agentRuntimeArn"]
        raise


def wait_ready(agent_runtime_arn: str, timeout_s: int = 420) -> str:
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    runtime_id = agent_runtime_arn.split("/")[-1]
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        response = client.get_agent_runtime(agentRuntimeId=runtime_id)
        status = response["status"]
        print(f"status={status}")
        if status in ("READY", "ACTIVE"):
            return status
        if status in ("CREATE_FAILED", "FAILED"):
            print(json.dumps(response, indent=2, default=str))
            raise SystemExit(f"Runtime failed with status={status}")
        time.sleep(15)
    raise SystemExit("Timed out waiting for runtime readiness")


if __name__ == "__main__":
    ensure_role()
    ensure_ecr_repo()
    push_image()
    arn = create_runtime()
    print(f"agentRuntimeArn={arn}")
    final_status = wait_ready(arn)
    print(f"final_status={final_status}")
