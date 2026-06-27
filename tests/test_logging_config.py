from __future__ import annotations

import logging
import stat
from pathlib import Path

from loguru import logger

from voice_toolbox.config import ConsoleLoggingConfig, FileLoggingConfig, LoggingConfig
from voice_toolbox.logging_config import InterceptHandler, configure_logging, sanitize_log_metadata


def test_configure_logging_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "voice-toolbox.log"
    config = LoggingConfig(
        console=ConsoleLoggingConfig(enabled=False),
        file=FileLoggingConfig(enabled=True, path=str(path), enqueue=False),
    )

    configure_logging(config, config_path=None)
    logging.getLogger("uvicorn.access").info("first")
    configure_logging(config, config_path=None)
    logging.getLogger("uvicorn.access").info("second")

    text = path.read_text(encoding="utf-8")
    assert text.count("first") == 1
    assert text.count("second") == 1
    assert logging.getLogger("uvicorn.access").handlers == []
    assert logging.getLogger("uvicorn.access").propagate is True
    root_handlers = logging.getLogger().handlers
    assert len(root_handlers) == 1
    assert isinstance(root_handlers[0], InterceptHandler)


def test_sanitize_log_metadata_allowlist() -> None:
    sanitized = sanitize_log_metadata(
        {
            "operation": "tts",
            "model": "mimo-v2.5-tts",
            "source_text": "secret raw text",
            "api_key": "tp-secret",
            "api_key_preview": "...cret",
            "data_url": "data:audio/wav;base64,abc",
            "artifact_ids": ["safe", "tp-secretvalue"],
            "source_text_length": 15,
        }
    )

    assert sanitized == {
        "operation": "tts",
        "model": "mimo-v2.5-tts",
        "source_text_length": 15,
    }


def test_log_file_never_contains_raw_request_values(tmp_path: Path) -> None:
    path = tmp_path / "voice.log"
    configure_logging(
        LoggingConfig(
            console=ConsoleLoggingConfig(enabled=False),
            file=FileLoggingConfig(enabled=True, path=str(path), enqueue=False),
        ),
        config_path=None,
    )

    logger.bind(
        **sanitize_log_metadata(
            {
                "operation": "tts",
                "source_text": "raw secret text",
                "style_instruction": "raw style",
                "voice_description": "raw voice",
                "transcript": "raw transcript",
                "sample_content": "raw sample",
                "payload": "data:audio/wav;base64,abcdef",
                "api_key": "tp-secret",
                "source_text_length": 15,
                "style_instruction_length": 9,
                "voice_description_length": 9,
            }
        )
    ).info("request completed")

    text = path.read_text(encoding="utf-8")
    assert "raw secret text" not in text
    assert "raw style" not in text
    assert "raw voice" not in text
    assert "raw transcript" not in text
    assert "raw sample" not in text
    assert "base64" not in text
    assert "tp-secret" not in text
    assert "request completed" in text


def test_uvicorn_access_log_query_string_is_redacted(tmp_path: Path) -> None:
    path = tmp_path / "voice.log"
    configure_logging(
        LoggingConfig(
            console=ConsoleLoggingConfig(enabled=False),
            file=FileLoggingConfig(enabled=True, path=str(path), enqueue=False),
        ),
        config_path=None,
    )

    logging.getLogger("uvicorn.access").info(
        '127.0.0.1:12345 - "GET /v1/tts/builtin?text=raw-secret&api_key=tp-secret HTTP/1.1" 200'
    )

    text = path.read_text(encoding="utf-8")
    assert "raw-secret" not in text
    assert "tp-secret" not in text
    assert "/v1/tts/builtin?..." in text


def test_log_interceptor_redacts_token_and_data_url_outside_query(tmp_path: Path) -> None:
    path = tmp_path / "voice.log"
    configure_logging(
        LoggingConfig(
            console=ConsoleLoggingConfig(enabled=False),
            file=FileLoggingConfig(enabled=True, path=str(path), enqueue=False),
        ),
        config_path=None,
    )

    logging.getLogger("uvicorn.error").info(
        "payload=data:audio/wav;base64,abcdef123456 key=tp-short"
    )

    text = path.read_text(encoding="utf-8")
    assert "abcdef123456" not in text
    assert "tp-short" not in text
    assert "data:...;base64,..." in text


def test_intercepted_exception_does_not_write_raw_traceback_or_args(tmp_path: Path) -> None:
    path = tmp_path / "voice.log"
    configure_logging(
        LoggingConfig(
            console=ConsoleLoggingConfig(enabled=False),
            file=FileLoggingConfig(enabled=True, path=str(path), enqueue=False),
        ),
        config_path=None,
    )

    try:
        raise RuntimeError("tp-short /Users/private/path")
    except RuntimeError:
        logging.getLogger("uvicorn.error").exception("failed")

    text = path.read_text(encoding="utf-8")
    assert "tp-short" not in text
    assert "/Users/private/path" not in text
    assert "Traceback" not in text
    assert "RuntimeError" in text


def test_log_file_permissions_are_private(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "voice.log"
    configure_logging(
        LoggingConfig(
            console=ConsoleLoggingConfig(enabled=False),
            file=FileLoggingConfig(enabled=True, path=str(path), enqueue=False),
        ),
        config_path=None,
    )

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_relative_file_path_resolves_against_config_dir(tmp_path: Path) -> None:
    config_path = tmp_path / "configs" / "voice_toolbox.toml"
    config_path.parent.mkdir()
    configure_logging(
        LoggingConfig(
            console=ConsoleLoggingConfig(enabled=False),
            file=FileLoggingConfig(enabled=True, path="logs/voice.log", enqueue=False),
        ),
        config_path=config_path,
    )

    logger.info("relative path works")

    assert (tmp_path / "configs" / "logs" / "voice.log").is_file()
