from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from loguru import logger

from voice_toolbox.artifacts import ALLOWED_METADATA_KEYS
from voice_toolbox.config_models import LoggingConfig

HUMAN_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"

LOG_METADATA_KEYS = frozenset(
    {
        *ALLOWED_METADATA_KEYS,
        "api_key_preview",
        "artifact_id",
        "artifact_ids",
        "config_path_name",
        "duration_ms",
        "elapsed_ms",
        "error_summary",
        "file_name",
        "http_method",
        "http_status",
        "operation_id",
        "path_name",
        "provider_type",
        "request_id",
        "source_text_length",
        "status",
        "status_code",
        "style_instruction_length",
        "voice_description_length",
    }
)

INTERCEPT_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "starlette")
QUERY_STRING_PATTERN = re.compile(r"(\s/[^\s?]*)(\?[^ \"]*)")


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        logger.opt(depth=6, exception=record.exc_info).log(
            level, _sanitize_log_message(record.getMessage())
        )


def sanitize_log_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in metadata.items()
        if key in LOG_METADATA_KEYS and _safe_log_metadata_value(value)
    }


def configure_logging(config: LoggingConfig, *, config_path: Path | None) -> None:
    logger.remove()
    if config.console.enabled:
        logger.add(
            sys.stderr,
            level=config.console.level,
            format=HUMAN_FORMAT,
            colorize=config.console.colorize,
        )
    if config.file.enabled:
        path = _resolve_log_path(config.file.path, config_path=config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            path,
            level=config.file.level,
            format=HUMAN_FORMAT,
            rotation=config.file.rotation,
            retention=config.file.retention,
            compression=config.file.compression,
            enqueue=config.file.enqueue,
        )

    root_logger = logging.getLogger()
    root_logger.handlers = [InterceptHandler()]
    root_logger.setLevel(logging.NOTSET)

    for name in INTERCEPT_LOGGERS:
        target = logging.getLogger(name)
        target.handlers = []
        target.propagate = True


def _resolve_log_path(path: str, *, config_path: Path | None) -> Path:
    log_path = Path(path)
    if not log_path.is_absolute() and config_path is not None:
        return config_path.parent / log_path
    return log_path


def _safe_log_metadata_value(value: object) -> bool:
    return value is None or isinstance(value, str | int | float | bool | tuple | list)


def _sanitize_log_message(message: str) -> str:
    sanitized = QUERY_STRING_PATTERN.sub(r"\1?...", message)
    return sanitized
