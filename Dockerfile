FROM python:3.12-slim AS builder

WORKDIR /app

# Copy build metadata + source
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir .

# --- Final stage: minimal runtime ---
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

# Copy source (needed for static files resolved via Path(__file__))
COPY src/ src/

# Mount points for host AI tool data (read-only)
# Usage: docker run -v ~/.claude:/data/.claude:ro -v ~/.cursor:/data/.cursor:ro ...
ENV CLAUDE_DIR=/data/.claude \
    CURSOR_DIR=/data/.cursor \
    KIRO_DIR=/data/.kiro \
    AGENTTOP_DIR=/data/.agenttop \
    PYTHONPATH=/app/src

EXPOSE 8420

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8420/api/stats')" || exit 1

CMD ["python", "-m", "uvicorn", "agenttop.web.server:app", \
     "--host", "0.0.0.0", "--port", "8420"]
