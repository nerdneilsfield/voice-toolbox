from __future__ import annotations

import logging
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
            "data_url": "data:audio/wav;base64,abc",
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
    assert "source_text_length" not in text


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
