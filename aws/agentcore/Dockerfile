# Lane B: AgentCore Runtime container (must be linux/arm64). Build from the repo root:
#   docker buildx build --platform linux/arm64 -f aws/agentcore/Dockerfile -t carerelay-agentcore --load .
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY data/cases ./data/cases
COPY data/output ./data/output
COPY data/network ./data/network
COPY data/reference ./data/reference

RUN pip install --no-cache-dir . bedrock-agentcore

COPY aws/agentcore/app.py ./app.py

ENV CARERELAY_DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "app.py"]
