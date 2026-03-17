#!/bin/sh
set -e
exec python -m uvicorn agenttop.web.server:app --host 0.0.0.0 --port 8420
