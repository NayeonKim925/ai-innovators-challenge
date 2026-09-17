"""Redeploys just the Lambda code (handler.py fix for the tool-name contract).

Run: python backend/app/llm/aws/update_lambda.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import boto3

REGION = "us-east-1"
HERE = Path(__file__).parent
LAMBDA_FUNCTION_NAME = "mfg-investigation-tools"

zip_path = HERE / "lambda_tools" / "handler.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.write(HERE / "lambda_tools" / "handler.py", arcname="handler.py")

client = boto3.client("lambda", region_name=REGION)
response = client.update_function_code(
    FunctionName=LAMBDA_FUNCTION_NAME, ZipFile=zip_path.read_bytes(), Publish=True
)
print(f"updated {response['FunctionArn']} to version {response['Version']}")
