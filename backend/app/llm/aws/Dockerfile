# AgentCore Runtime container for the manufacturing investigation explainer.
# Build context MUST be the repository root (see build_and_deploy.py).
FROM --platform=linux/arm64 python:3.12-slim

WORKDIR /app

COPY backend/app/llm/aws/requirements.txt ./requirements.txt
COPY backend/app ./backend/app

RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app/backend/app/llm/aws

EXPOSE 8080

CMD ["python", "agentcore_main.py"]
