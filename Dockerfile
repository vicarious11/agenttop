FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir .

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENV CLAUDE_DIR=/data/.claude \
    CURSOR_DIR=/data/.cursor \
    KIRO_DIR=/data/.kiro \
    AGENTTOP_DIR=/data/.agenttop \
    PYTHONPATH=/app/src \
    AGENTTOP_LLM_BASE_URL=http://host.docker.internal:11434

EXPOSE 8420

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8420/api/stats')" || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
