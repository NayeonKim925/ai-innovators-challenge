"""Deploys the Lambda tool handler + AgentCore Gateway + Gateway Target
(task: connect get_root_cause_ranking / get_fault_reference as real tools).

Run: python backend/app/llm/aws/deploy_gateway.py
"""

from __future__ import annotations

import json
import os
import time
import zipfile
from pathlib import Path

import boto3

REGION = "us-east-1"
HERE = Path(__file__).parent
LAMBDA_FUNCTION_NAME = "mfg-investigation-tools"
LAMBDA_ROLE_NAME = "mfg-investigation-tools-lambda-role"
GATEWAY_ROLE_NAME = "mfg-investigation-gateway-role"
GATEWAY_NAME = "mfg-investigation-gateway"

sts = boto3.client("sts", region_name=REGION)
ACCOUNT_ID = sts.get_caller_identity()["Account"]
DDB_TABLE_NAME = os.getenv("INVESTIGATION_DDB_TABLE", "mfg-investigations")


def _zip_handler() -> bytes:
    zip_path = HERE / "lambda_tools" / "handler.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(HERE / "lambda_tools" / "handler.py", arcname="handler.py")
    return zip_path.read_bytes()


def ensure_lambda_role() -> str:
    iam = boto3.client("iam")
    role_arn = f"arn:aws:iam::{ACCOUNT_ID}:role/{LAMBDA_ROLE_NAME}"
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}
        ],
    }
    try:
        iam.create_role(
            RoleName=LAMBDA_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Execution role for the mfg-investigation-tools Lambda (AgentCore Gateway target)",
        )
        print(f"created role {LAMBDA_ROLE_NAME}")
        time.sleep(10)
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"role {LAMBDA_ROLE_NAME} already exists")
    iam.attach_role_policy(
        RoleName=LAMBDA_ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    )
    iam.put_role_policy(
        RoleName=LAMBDA_ROLE_NAME,
        PolicyName="ReadInvestigationResults",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["dynamodb:GetItem"],
                        "Resource": f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/{DDB_TABLE_NAME}",
                    }
                ],
            }
        ),
    )
    return role_arn


def ensure_lambda_function(role_arn: str) -> str:
    client = boto3.client("lambda", region_name=REGION)
    zip_bytes = _zip_handler()
    try:
        response = client.create_function(
            FunctionName=LAMBDA_FUNCTION_NAME,
            Runtime="python3.12",
            Role=role_arn,
            Handler="handler.handler",
            Code={"ZipFile": zip_bytes},
            Description="ADR-0002 fallback tool handler for the AgentCore Gateway (task #13).",
            Timeout=10,
            Environment={"Variables": {"INVESTIGATION_DDB_TABLE": DDB_TABLE_NAME, "AWS_REGION": REGION}},
            Publish=True,
        )
        print(f"created function {response['FunctionArn']}")
        return response["FunctionArn"]
    except client.exceptions.ResourceConflictException:
        client.update_function_code(FunctionName=LAMBDA_FUNCTION_NAME, ZipFile=zip_bytes, Publish=True)
        client.update_function_configuration(
            FunctionName=LAMBDA_FUNCTION_NAME,
            Environment={
                "Variables": {"INVESTIGATION_DDB_TABLE": DDB_TABLE_NAME, "AWS_REGION": REGION}
            },
        )
        response = client.get_function(FunctionName=LAMBDA_FUNCTION_NAME)
        print(f"updated function {response['Configuration']['FunctionArn']}")
        return response["Configuration"]["FunctionArn"]


def allow_gateway_to_invoke_lambda(lambda_arn: str) -> None:
    client = boto3.client("lambda", region_name=REGION)
    try:
        client.add_permission(
            FunctionName=LAMBDA_FUNCTION_NAME,
            StatementId="AllowAgentCoreGatewayInvoke",
            Action="lambda:InvokeFunction",
            Principal="bedrock-agentcore.amazonaws.com",
            SourceAccount=ACCOUNT_ID,
        )
        print("added resource policy for AgentCore Gateway invoke")
    except client.exceptions.ResourceConflictException:
        print("resource policy already present")


def ensure_gateway_role(lambda_arn: str) -> str:
    iam = boto3.client("iam")
    role_arn = f"arn:aws:iam::{ACCOUNT_ID}:role/{GATEWAY_ROLE_NAME}"
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT_ID}},
            }
        ],
    }
    try:
        iam.create_role(
            RoleName=GATEWAY_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="AgentCore Gateway role: allowed to invoke the tools Lambda",
        )
        print(f"created role {GATEWAY_ROLE_NAME}")
        time.sleep(10)
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"role {GATEWAY_ROLE_NAME} already exists")

    invoke_policy = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": lambda_arn}],
    }
    iam.put_role_policy(
        RoleName=GATEWAY_ROLE_NAME,
        PolicyName="InvokeToolsLambda",
        PolicyDocument=json.dumps(invoke_policy),
    )
    return role_arn


def ensure_gateway(role_arn: str) -> str:
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    try:
        response = client.create_gateway(
            name=GATEWAY_NAME,
            description="ADR-0002: exposes get_root_cause_ranking / get_fault_reference as MCP tools.",
            roleArn=role_arn,
            protocolType="MCP",
            protocolConfiguration={"mcp": {"supportedVersions": ["2025-03-26"]}},
            authorizerType="AWS_IAM",
        )
        print(json.dumps(response, indent=2, default=str))
        return response["gatewayId"]
    except client.exceptions.ConflictException:
        gateways = client.list_gateways()
        for gw in gateways["items"]:
            if gw["name"] == GATEWAY_NAME:
                print(f"gateway already exists: {gw['gatewayId']}")
                return gw["gatewayId"]
        raise


def wait_gateway_ready(gateway_id: str, timeout_s: int = 180) -> str:
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        response = client.get_gateway(gatewayIdentifier=gateway_id)
        status = response["status"]
        print(f"gateway status={status}")
        if status in ("READY", "ACTIVE"):
            return status
        if "FAILED" in status:
            print(json.dumps(response, indent=2, default=str))
            raise SystemExit(f"Gateway failed with status={status}")
        time.sleep(10)
    raise SystemExit("Timed out waiting for gateway readiness")


def ensure_gateway_target(gateway_id: str, lambda_arn: str) -> str:
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    tool_schema = json.loads((HERE / "gateway_tool_schema.json").read_text(encoding="utf-8"))
    try:
        response = client.create_gateway_target(
            gatewayIdentifier=gateway_id,
            name="investigation-tools",
            description="get_root_cause_ranking / get_fault_reference backed by the mfg-investigation-tools Lambda.",
            targetConfiguration={
                "mcp": {
                    "lambda": {
                        "lambdaArn": lambda_arn,
                        "toolSchema": {"inlinePayload": tool_schema},
                    }
                }
            },
            credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        )
        print(json.dumps(response, indent=2, default=str))
        return response["targetId"]
    except client.exceptions.ConflictException:
        targets = client.list_gateway_targets(gatewayIdentifier=gateway_id)
        for target in targets["items"]:
            if target["name"] == "investigation-tools":
                print(f"target already exists: {target['targetId']}")
                return target["targetId"]
        raise


if __name__ == "__main__":
    lambda_role_arn = ensure_lambda_role()
    lambda_arn = ensure_lambda_function(lambda_role_arn)
    allow_gateway_to_invoke_lambda(lambda_arn)
    gateway_role_arn = ensure_gateway_role(lambda_arn)
    gateway_id = ensure_gateway(gateway_role_arn)
    status = wait_gateway_ready(gateway_id)
    print(f"gateway_id={gateway_id} status={status}")
    target_id = ensure_gateway_target(gateway_id, lambda_arn)
    print(f"target_id={target_id}")
