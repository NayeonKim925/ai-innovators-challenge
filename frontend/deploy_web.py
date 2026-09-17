"""Replace only the existing ECS frontend image; preserve roles, network and secrets.

Run from repo root: AWS_PROFILE=ai-innovators uv run --extra deploy python frontend/deploy_web.py
No resources or IAM permissions are created. The previous image remains in ECR.
"""

from __future__ import annotations

import base64
import copy
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import boto3


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    session = boto3.Session(region_name=region)
    account = session.client("sts").get_caller_identity()["Account"]
    ecs = session.client("ecs")
    ecr = session.client("ecr")
    service_arn = f"arn:aws:ecs:{region}:{account}:service/default/mfg-investigation-frontend"
    service = ecs.describe_express_gateway_service(serviceArn=service_arn)["service"]
    configurations = service.get("activeConfigurations", [])
    if len(configurations) != 1:
        raise SystemExit("Expected one stable frontend configuration; no change made.")
    deployments = ecs.describe_services(cluster="default", services=[service_arn])["services"][0][
        "deployments"
    ]
    if any(d.get("rolloutState") != "COMPLETED" for d in deployments):
        raise SystemExit("An existing rollout is not complete; no change made.")
    config = configurations[0]
    container = copy.deepcopy(config["primaryContainer"])
    env = {e["name"]: e["value"] for e in container.get("environment", [])}
    if not env.get("BACKEND_API_TOKEN") or not env.get("BACKEND_URL", "").startswith("https://"):
        raise SystemExit("Existing secure backend connection is missing; no change made.")
    tag = "web-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    repository = "mfg-investigation-frontend"
    registry = f"{account}.dkr.ecr.{region}.amazonaws.com"
    image = f"{registry}/{repository}:{tag}"
    arch = "arm64" if config.get("cpuArchitecture") == "ARM64" else "amd64"
    subprocess.run(
        [
            "docker",
            "build",
            "--platform",
            f"linux/{arch}",
            "-f",
            "frontend/Dockerfile.web",
            "-t",
            image,
            ".",
        ],
        cwd=root,
        check=True,
    )
    credentials = ecr.get_authorization_token()["authorizationData"][0]
    username, password = base64.b64decode(credentials["authorizationToken"]).decode().split(":", 1)
    subprocess.run(
        ["docker", "login", "--username", username, "--password-stdin", registry],
        input=password,
        text=True,
        check=True,
    )
    subprocess.run(["docker", "push", image], check=True)
    digest = ecr.describe_images(repositoryName=repository, imageIds=[{"imageTag": tag}])[
        "imageDetails"
    ][0]["imageDigest"]
    container["image"] = f"{registry}/{repository}@{digest}"
    print(f"previous_image={config['primaryContainer']['image']}", flush=True)
    print(f"new_image={container['image']}", flush=True)
    ecs.update_express_gateway_service(
        serviceArn=service_arn, primaryContainer=container, healthCheckPath="/healthz"
    )
    print(
        "Frontend update submitted. Existing network, roles, scaling "
        "and backend credentials preserved."
    )
    print(
        "Monitor with describe_services; do not print the full service configuration "
        "(it contains secrets)."
    )


if __name__ == "__main__":
    main()
