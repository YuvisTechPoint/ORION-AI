import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.utils.correlation import get_correlation_id, get_trace_id
from app.utils.text_analysis import redact_secrets

_STANDARD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime"}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if settings.is_production:
            message = redact_secrets(message)
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": message,
        }
        correlation_id = get_correlation_id()
        trace_id = get_trace_id()
        if correlation_id:
            payload["correlation_id"] = correlation_id
        if trace_id:
            payload["trace_id"] = trace_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


JsonFormatter = JSONFormatter


class _ColorFormatter(logging.Formatter):
    _COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[41m",
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if not sys.stdout.isatty():
            return text
        color = self._COLORS.get(record.levelname, "")
        return f"{color}{text}{self._RESET}" if color else text


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    if settings.is_production:
        handler.setFormatter(JSONFormatter())
        logger.setLevel(logging.INFO)
    else:
        handler.setFormatter(
            _ColorFormatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )
        logger.setLevel(logging.DEBUG)

    logger.addHandler(handler)
    logger.propagate = False
    return logger


pipeline_logger = get_logger("pipeline")
