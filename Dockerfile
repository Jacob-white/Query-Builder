FROM python:3.12-slim

WORKDIR /app

# Install curl for container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python package metadata and source
COPY pyproject.toml README.md LICENSE ./
COPY query_builder ./query_builder

# Install Query-Builder engine with FastAPI server, PostgreSQL, MySQL, DuckDB, and export extras
RUN pip install --no-cache-dir -e ".[server,postgresql,mysql,duckdb,sqlalchemy]" \
    psycopg2-binary>=2.9.9 \
    pyarrow>=14.0.0 \
    openpyxl>=3.1.0

# Copy Fullstack Starter backend + compiled React Studio SPA (examples/fullstack_starter/frontend/dist)
COPY examples/fullstack_starter ./examples/fullstack_starter

EXPOSE 8086

ENV HOST=0.0.0.0 \
    PORT=8086 \
    QB_DEFAULT_DB=starter_demo

CMD ["uvicorn", "backend.main:app", "--app-dir", "/app/examples/fullstack_starter", "--host", "0.0.0.0", "--port", "8086"]
