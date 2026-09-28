# syntax=docker/dockerfile:1
# The Project Corpus Generator as a lake library agent (lake#263): private on Docker Hub as
# oramasearch/agent-project-corpus. It records one worked example on the person's own data per
# turn, reading their workspace through lake; it lands and writes nothing.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --uid 10001 --create-home agent
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PORT=8080
USER 10001
EXPOSE 8080
ENTRYPOINT ["agent-project-corpus-serve"]
