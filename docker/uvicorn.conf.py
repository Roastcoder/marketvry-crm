# Uvicorn configuration reference for Horilla-CRM
#
# Unlike Gunicorn (used in Horilla-HR), Uvicorn does not support a --config file.
# These values are passed as CLI arguments in the Dockerfile CMD instead.
# This file documents the configuration for reference and environment overrides.
#
# To override at runtime, set environment variables:
#   UVICORN_WORKERS=4
#   UVICORN_LOG_LEVEL=warning
#   UVICORN_RELOAD=true

import multiprocessing
import os

# Bind settings
HOST = os.environ.get("UVICORN_HOST", "0.0.0.0")
PORT = int(os.environ.get("UVICORN_PORT", "8000"))

# Worker settings — matches Gunicorn formula: max(2, min(CPU*2+1, 8))
WORKERS = int(
    os.environ.get(
        "UVICORN_WORKERS", max(2, min(multiprocessing.cpu_count() * 2 + 1, 8))
    )
)

# Logging
LOG_LEVEL = os.environ.get("UVICORN_LOG_LEVEL", "info")

# Development settings
RELOAD = os.environ.get("UVICORN_RELOAD", "false").lower() == "true"

# WebSocket settings (CRM uses Django Channels for real-time notifications)
WS_PING_INTERVAL = 20
WS_PING_TIMEOUT = 20

# ASGI lifespan — "off" because Django Channels' ProtocolTypeRouter
# does not handle the "lifespan" scope type
LIFESPAN = "off"

# Process naming
PROC_NAME = "horilla-crm"
