"""Run the gateway: python -m llmgateway  (from the day30 directory).

Exactly one worker: the rate limiter and the generation queue live in process
memory (see README).
"""
from __future__ import annotations

import uvicorn

from . import config
from .app import build_app

app = build_app()


def main():
    uvicorn.run(app, host=config.SERVICE_HOST, port=config.SERVICE_PORT, workers=1, log_level="info")


if __name__ == "__main__":
    main()
