from __future__ import annotations

import logging
import re
import sys
import traceback
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType

from loguru import logger

from voice_toolbox.artifacts import ALLOWED_METADATA_KEYS
from voice_toolbox.config_models import LoggingConfig

HUMAN_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
LOGURU_INTERCEPT_DEPTH = 6  # stdlib logging -> InterceptHandler -> Loguru call stack depth.

LOG_METADATA_KEYS = frozenset(
    {
        *ALLOWED_METADATA_KEYS,
        "artifact_id",
        "artifact_ids",
        "clone_reference_text_length",
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
SECRET_TOKEN_PATTERN = re.compile(r"\b(?:tp|sk)-[^\s\"']+\b")
DATA_URL_PATTERN = re.compile(r"data:[^;\s]+;base64,[A-Za-z0-9+/=_-]+")
BASE64_LABEL_PATTERN = re.compile(r"(base64[=:])([A-Za-z0-9+/=_-]{8,})", re.IGNORECASE)
LOCAL_PATH_PATTERN = re.compile(r"(?<!\w)/(?:Users|private|var|tmp|Volumes)/[^\s\"']+")


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        message = _sanitize_log_message(record.getMessage())
        if record.exc_info and record.exc_info[0] is not None:
            message = f"{message}\n{_format_safe_exception(record.exc_info)}"
        logger.opt(depth=LOGURU_INTERCEPT_DEPTH).log(level, message)


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
            backtrace=False,
            diagnose=False,
        )
    if config.file.enabled:
        path = _resolve_log_path(config.file.path, config_path=config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
        logger.add(
            path,
            level=config.file.level,
            format=HUMAN_FORMAT,
            rotation=config.file.rotation,
            retention=config.file.retention,
            compression=config.file.compression,
            enqueue=config.file.enqueue,
            backtrace=False,
            diagnose=False,
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
    if value is None or isinstance(value, int | float | bool):
        return True
    if isinstance(value, str):
        return _is_safe_log_string(value)
    if isinstance(value, tuple | list):
        return all(_safe_log_metadata_value(item) for item in value)
    return False


def _sanitize_log_message(message: str) -> str:
    sanitized = QUERY_STRING_PATTERN.sub(r"\1?...", message)
    sanitized = DATA_URL_PATTERN.sub("data:...;base64,...", sanitized)
    sanitized = BASE64_LABEL_PATTERN.sub(r"\1...", sanitized)
    sanitized = SECRET_TOKEN_PATTERN.sub("configured", sanitized)
    sanitized = LOCAL_PATH_PATTERN.sub(_mask_path_match, sanitized)
    return sanitized


def _format_safe_exception(
    exc_info: tuple[type[BaseException], BaseException, TracebackType | None],
) -> str:
    exc_type, exc, traceback_object = exc_info
    frames = traceback.extract_tb(traceback_object) if traceback_object is not None else []
    lines = ["Traceback (sanitized):"]
    for frame in frames:
        path = Path(frame.filename)
        lines.append(f'  File "{path.name}", line {frame.lineno}, in {frame.name}')
    lines.append(f"{exc_type.__name__}: {_sanitize_log_message(str(exc))}")
    return "\n".join(lines)


def _is_safe_log_string(value: str) -> bool:
    return not (
        SECRET_TOKEN_PATTERN.search(value)
        or DATA_URL_PATTERN.search(value)
        or LOCAL_PATH_PATTERN.search(value)
        or "base64," in value.lower()
    )


def _mask_path_match(match: re.Match[str]) -> str:
    return f"[path:{Path(match.group(0)).name}]"
