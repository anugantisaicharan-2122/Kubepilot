# KubePilot — container image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir .

# The server speaks MCP over stdio; run it attached to your agent client.
# Mount a kubeconfig and configure via environment, e.g.:
#   docker run -i --rm \
#     -v ~/.kube/config:/root/.kube/config:ro \
#     -e KUBEPILOT_READ_ONLY=true \
#     kubepilot:latest
ENTRYPOINT ["kubepilot"]
