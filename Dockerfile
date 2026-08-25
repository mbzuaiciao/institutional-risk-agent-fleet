FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PORT=8080

WORKDIR /app

RUN pip install --no-cache-dir uv==0.12.5
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY app ./app
COPY data ./data
RUN uv sync --locked --no-dev

ENV PATH="/opt/venv/bin:$PATH"
USER 65532:65532

CMD ["python", "-m", "institutional_risk_fleet.cloud_entrypoint"]
