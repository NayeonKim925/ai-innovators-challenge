# App Runner container image for the Streamlit demo UI (task #28).
# Build context MUST be the repository root:
#   docker build -f frontend/Dockerfile -t mfg-investigation-frontend .
FROM python:3.12-slim

WORKDIR /app

COPY frontend/app.py ./app.py

RUN pip install --no-cache-dir "streamlit>=1.38,<2" "requests>=2.32,<3"

EXPOSE 8080

# App Runner's default health check just needs a 2xx on the listening port.
# BACKEND_URL is provided as an App Runner service environment variable at
# deploy time (backend/deploy_lambda_api.py's endpoint) -- this Dockerfile
# never hardcodes it, matching app.py's `os.getenv("BACKEND_URL", ...)` design.
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0", "--server.headless=true"]
