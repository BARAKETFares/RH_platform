"""
Configuration du logging structuré.

En production (LOG_FORMAT=json) : logs JSON sur stdout (compatibles ELK / Loki).
En développement (LOG_FORMAT=text) : logs colorés lisibles en console.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from flask import Flask


def configure_logging(app: Flask) -> None:
    log_level = getattr(logging, app.config.get("LOG_LEVEL", "INFO").upper())
    log_format = app.config.get("LOG_FORMAT", "text")

    if log_format == "json":
        _configure_json_logging(app, log_level)
    else:
        _configure_text_logging(app, log_level)


def _configure_text_logging(app: Flask, level: int) -> None:
    fmt = "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    # Réduire le bruit SQLAlchemy en dev
    if level == logging.DEBUG:
        logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)


def _configure_json_logging(app: Flask, level: int) -> None:
    """Logging JSON minimal (structlog recommandé en production)."""
    import json

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
                "level":     record.levelname,
                "logger":    record.name,
                "message":   record.getMessage(),
            }
            if record.exc_info:
                payload["exception"] = self.formatException(record.exc_info)
            return json.dumps(payload, ensure_ascii=False)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
