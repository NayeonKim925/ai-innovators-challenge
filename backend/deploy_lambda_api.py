"""Deploys the FastAPI investigation API to AWS Lambda (container image) +
API Gateway HTTP API (task #26, 2-D).

Run: python backend/deploy_lambda_api.py
"""

from __future__ import annotations

import json
import os
import subprocess
import time

import boto3

REGION = "us-east-1"
ECR_REPO_NAME = "mfg-investigation-api"
IMAGE_TAG = "latest"
LOCAL_IMAGE = "mfg-investigation-api:latest"
LAMBDA_FUNCTION_NAME = "mfg-investigation-api"
WORKER_FUNCTION_NAME = "mfg-investigation-narrative-worker"
LAMBDA_ROLE_NAME = "mfg-investigation-api-lambda-role"
API_NAME = "mfg-investigation-api"
LLM_JOB_QUEUE_NAME = os.getenv("LLM_JOB_QUEUE_NAME", "mfg-investigation-narrative-jobs")
DDB_TABLE_NAME = os.getenv("INVESTIGATION_DDB_TABLE", "mfg-investigations")
CASE_DDB_TABLE_NAME = os.getenv("CASE_DDB_TABLE", "mfg-investigation-cases")
DEPLOY_ASYNC_LLM = os.getenv("DEPLOY_ASYNC_LLM", "true").lower() in {"1", "true", "yes"}
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")
BEDROCK_MODEL_ARN = os.getenv("BEDROCK_MODEL_ARN", "")
BEDROCK_GUARDRAIL_ARN = os.getenv("BEDROCK_GUARDRAIL_ARN", "")
BEDROCK_GUARDRAIL_ID = os.getenv("BEDROCK_GUARDRAIL_ID", "")

sts = boto3.client("sts", region_name=REGION)
ACCOUNT_ID = sts.get_caller_identity()["Account"]
ECR_URI = f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/{ECR_REPO_NAME}:{IMAGE_TAG}"
LAMBDA_ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/{LAMBDA_ROLE_NAME}"
LLM_JOB_QUEUE_ARN = f"arn:aws:sqs:{REGION}:{ACCOUNT_ID}:{LLM_JOB_QUEUE_NAME}"


def ensure_lambda_role() -> str:
    iam = boto3.client("iam")
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    try:
        iam.create_role(
            RoleName=LAMBDA_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Execution role for the mfg-investigation-api Lambda (task #17/#26).",
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
        PolicyName="mfg-investigation-runtime-access",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": "bedrock:InvokeModel",
                        "Resource": BEDROCK_MODEL_ARN,
                    },
                    {
                        "Effect": "Allow",
                        "Action": "bedrock:ApplyGuardrail",
                        "Resource": BEDROCK_GUARDRAIL_ARN,
                    },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "dynamodb:GetItem",
                            "dynamodb:PutItem",
                            "dynamodb:UpdateItem",
                            "dynamodb:Scan",
                        ],
                        "Resource": [
                            f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/{DDB_TABLE_NAME}",
                            f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/{CASE_DDB_TABLE_NAME}",
                        ],
                    },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "sqs:SendMessage",
                            "sqs:ReceiveMessage",
                            "sqs:DeleteMessage",
                            "sqs:GetQueueAttributes",
                        ],
                        "Resource": LLM_JOB_QUEUE_ARN,
                    },
                ],
            }
        ),
    )
    return LAMBDA_ROLE_ARN


def ensure_ecr_repo() -> None:
    ecr = boto3.client("ecr", region_name=REGION)
    try:
        ecr.describe_repositories(repositoryNames=[ECR_REPO_NAME])
        print(f"ECR repo {ECR_REPO_NAME} already exists")
    except ecr.exceptions.RepositoryNotFoundException:
        ecr.create_repository(repositoryName=ECR_REPO_NAME)
        print(f"created ECR repo {ECR_REPO_NAME}")


def ensure_investigation_table() -> None:
    dynamodb = boto3.client("dynamodb", region_name=REGION)
    try:
        dynamodb.describe_table(TableName=DDB_TABLE_NAME)
        print(f"DynamoDB table {DDB_TABLE_NAME} already exists")
    except dynamodb.exceptions.ResourceNotFoundException:
        dynamodb.create_table(
            TableName=DDB_TABLE_NAME,
            KeySchema=[{"AttributeName": "investigation_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "investigation_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"created DynamoDB table {DDB_TABLE_NAME}")
    waiter = dynamodb.get_waiter("table_exists")
    waiter.wait(TableName=DDB_TABLE_NAME, WaiterConfig={"Delay": 2, "MaxAttempts": 30})
    print(f"DynamoDB table {DDB_TABLE_NAME} is ready")


def ensure_case_table() -> None:
    """Create the separate case-state table used by the Lambda API."""

    dynamodb = boto3.client("dynamodb", region_name=REGION)
    try:
        dynamodb.describe_table(TableName=CASE_DDB_TABLE_NAME)
        print(f"DynamoDB table {CASE_DDB_TABLE_NAME} already exists")
    except dynamodb.exceptions.ResourceNotFoundException:
        dynamodb.create_table(
            TableName=CASE_DDB_TABLE_NAME,
            KeySchema=[{"AttributeName": "case_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "case_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"created DynamoDB table {CASE_DDB_TABLE_NAME}")
    waiter = dynamodb.get_waiter("table_exists")
    waiter.wait(
        TableName=CASE_DDB_TABLE_NAME,
        WaiterConfig={"Delay": 2, "MaxAttempts": 30},
    )
    print(f"DynamoDB table {CASE_DDB_TABLE_NAME} is ready")


def ensure_job_queue() -> tuple[str, str]:
    sqs = boto3.client("sqs", region_name=REGION)
    response = sqs.create_queue(
        QueueName=LLM_JOB_QUEUE_NAME,
        Attributes={"VisibilityTimeout": "120", "ReceiveMessageWaitTimeSeconds": "10"},
    )
    queue_url = response["QueueUrl"]
    attributes = sqs.get_queue_attributes(
        QueueUrl=queue_url, AttributeNames=["QueueArn"]
    )["Attributes"]
    print(f"SQS narrative queue ready: {queue_url}")
    return queue_url, attributes["QueueArn"]


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


def _runtime_environment(queue_url: str) -> dict[str, str]:
    return {
        "CORS_ORIGINS": os.getenv("CORS_ORIGINS", "http://localhost:8501"),
        "DEPLOYMENT_ENV": "aws",
        "INVESTIGATION_DDB_TABLE": DDB_TABLE_NAME,
        "CASE_DDB_TABLE": CASE_DDB_TABLE_NAME,
        "LLM_JOB_QUEUE_URL": queue_url,
        "BEDROCK_REGION": REGION,
        "BEDROCK_MODEL_ID": os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6"),
        "LLM_TIMEOUT_S": os.getenv("LLM_TIMEOUT_S", "8"),
        "BEDROCK_GUARDRAIL_ID": BEDROCK_GUARDRAIL_ID,
        "BEDROCK_GUARDRAIL_VERSION": os.getenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT"),
        "LLM_REQUIRE_GUARDRAIL": "true",
        "API_AUTH_TOKEN": API_AUTH_TOKEN,
    }


def ensure_lambda_function(role_arn: str, queue_url: str) -> str:
    client = boto3.client("lambda", region_name=REGION)
    environment = {"Variables": _runtime_environment(queue_url)}
    try:
        response = client.create_function(
            FunctionName=LAMBDA_FUNCTION_NAME,
            PackageType="Image",
            Code={"ImageUri": ECR_URI},
            Role=role_arn,
            Description="FastAPI manufacturing investigation API (task #17/#26).",
            Timeout=30,
            MemorySize=1024,
            Environment=environment,
        )
        print(f"created function {response['FunctionArn']}")
        return response["FunctionArn"]
    except client.exceptions.ResourceConflictException:
        client.update_function_code(FunctionName=LAMBDA_FUNCTION_NAME, ImageUri=ECR_URI)
        client.get_waiter("function_updated").wait(FunctionName=LAMBDA_FUNCTION_NAME)
        client.update_function_configuration(
            FunctionName=LAMBDA_FUNCTION_NAME,
            Timeout=30,
            MemorySize=1024,
            Environment=environment,
        )
        response = client.get_function(FunctionName=LAMBDA_FUNCTION_NAME)
        print(f"updated function {response['Configuration']['FunctionArn']}")
        return response["Configuration"]["FunctionArn"]


def ensure_worker_function(role_arn: str, queue_url: str) -> str:
    client = boto3.client("lambda", region_name=REGION)
    environment = {"Variables": _runtime_environment(queue_url)}
    image_config = {"Command": ["llm_job_handler.handler"]}
    try:
        response = client.create_function(
            FunctionName=WORKER_FUNCTION_NAME,
            PackageType="Image",
            Code={"ImageUri": ECR_URI},
            Role=role_arn,
            Description="Durable Bedrock narrative worker for manufacturing investigations.",
            Timeout=60,
            MemorySize=1024,
            Environment=environment,
            ImageConfig=image_config,
        )
        print(f"created worker {response['FunctionArn']}")
        return response["FunctionArn"]
    except client.exceptions.ResourceConflictException:
        client.update_function_code(FunctionName=WORKER_FUNCTION_NAME, ImageUri=ECR_URI)
        client.get_waiter("function_updated").wait(FunctionName=WORKER_FUNCTION_NAME)
        client.update_function_configuration(
            FunctionName=WORKER_FUNCTION_NAME,
            Timeout=60,
            MemorySize=1024,
            Environment=environment,
            ImageConfig=image_config,
        )
        response = client.get_function(FunctionName=WORKER_FUNCTION_NAME)
        print(f"updated worker {response['Configuration']['FunctionArn']}")
        return response["Configuration"]["FunctionArn"]


def wait_lambda_active(timeout_s: int = 180) -> None:
    client = boto3.client("lambda", region_name=REGION)
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        response = client.get_function(FunctionName=LAMBDA_FUNCTION_NAME)
        state = response["Configuration"]["State"]
        print(f"lambda state={state}")
        if state == "Active":
            return
        if state == "Failed":
            print(json.dumps(response["Configuration"], indent=2, default=str))
            raise SystemExit("Lambda function failed to become active")
        time.sleep(5)
    raise SystemExit("Timed out waiting for Lambda to become Active")


def wait_worker_active(timeout_s: int = 180) -> None:
    client = boto3.client("lambda", region_name=REGION)
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        response = client.get_function(FunctionName=WORKER_FUNCTION_NAME)
        state = response["Configuration"]["State"]
        print(f"worker state={state}")
        if state == "Active":
            return
        if state == "Failed":
            raise SystemExit("Narrative worker failed to become active")
        time.sleep(5)
    raise SystemExit("Timed out waiting for narrative worker to become Active")


def ensure_worker_event_source(worker_arn: str, queue_arn: str) -> None:
    lambda_client = boto3.client("lambda", region_name=REGION)
    mappings = lambda_client.list_event_source_mappings(
        EventSourceArn=queue_arn, FunctionName=WORKER_FUNCTION_NAME
    )["EventSourceMappings"]
    if mappings:
        print("SQS event source mapping already exists")
        return
    lambda_client.create_event_source_mapping(
        EventSourceArn=queue_arn,
        FunctionName=worker_arn,
        Enabled=True,
        BatchSize=1,
    )
    print("created SQS event source mapping")


def ensure_http_api(lambda_arn: str) -> str:
    apigw = boto3.client("apigatewayv2", region_name=REGION)
    apis = apigw.get_apis()
    for api in apis["Items"]:
        if api["Name"] == API_NAME:
            print(f"HTTP API already exists: {api['ApiId']}")
            return api["ApiId"]

    response = apigw.create_api(
        Name=API_NAME,
        ProtocolType="HTTP",
        Target=lambda_arn,
    )
    api_id = response["ApiId"]
    print(f"created HTTP API {api_id}")
    return api_id


def allow_apigw_to_invoke_lambda(api_id: str) -> None:
    lambda_client = boto3.client("lambda", region_name=REGION)
    try:
        lambda_client.add_permission(
            FunctionName=LAMBDA_FUNCTION_NAME,
            StatementId="AllowAPIGatewayInvoke",
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT_ID}:{api_id}/*/*",
        )
        print("added resource policy for API Gateway invoke")
    except lambda_client.exceptions.ResourceConflictException:
        print("resource policy already present")


def get_api_endpoint(api_id: str) -> str:
    apigw = boto3.client("apigatewayv2", region_name=REGION)
    response = apigw.get_api(ApiId=api_id)
    return response["ApiEndpoint"]


if __name__ == "__main__":
    if CASE_DDB_TABLE_NAME == DDB_TABLE_NAME:
        raise SystemExit(
            "CASE_DDB_TABLE must differ from INVESTIGATION_DDB_TABLE: their primary keys differ."
        )
    if not API_AUTH_TOKEN:
        raise SystemExit("Set API_AUTH_TOKEN before deploying a public API.")
    if not BEDROCK_MODEL_ARN:
        raise SystemExit("Set BEDROCK_MODEL_ARN before deploying a Bedrock-backed API.")
    if not BEDROCK_GUARDRAIL_ID or not BEDROCK_GUARDRAIL_ARN:
        raise SystemExit(
            "Set BEDROCK_GUARDRAIL_ID and BEDROCK_GUARDRAIL_ARN before deploying a guarded API."
        )
    role_arn = ensure_lambda_role()
    ensure_ecr_repo()
    ensure_investigation_table()
    ensure_case_table()
    if DEPLOY_ASYNC_LLM:
        queue_url, queue_arn = ensure_job_queue()
    else:
        queue_url, queue_arn = "", ""
        print("async LLM worker deployment disabled (DEPLOY_ASYNC_LLM=false)")
    push_image()
    lambda_arn = ensure_lambda_function(role_arn, queue_url)
    wait_lambda_active()
    if DEPLOY_ASYNC_LLM:
        worker_arn = ensure_worker_function(role_arn, queue_url)
        wait_worker_active()
        ensure_worker_event_source(worker_arn, queue_arn)
    api_id = ensure_http_api(lambda_arn)
    allow_apigw_to_invoke_lambda(api_id)
    endpoint = get_api_endpoint(api_id)
    print(f"api_id={api_id}")
    print(f"endpoint={endpoint}")
