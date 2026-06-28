from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from voice_toolbox.config_models import AppConfig
from voice_toolbox_api import main as api_main
from voice_toolbox_api import server


def test_server_main_replays_config_warnings_only_from_create_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "voice_toolbox.toml"
    config_path.write_text("[logging.console]\nenabled = false\n", encoding="utf-8")
    monkeypatch.setenv("VOICE_TOOLBOX_CONFIG", str(config_path))
    monkeypatch.setenv("MIMO_BASE_URL", "https://ignored.example/v1")

    replay_calls: list[tuple[Path | None, dict[str, str]]] = []
    run_calls: list[dict[str, Any]] = []

    def record_replay(config: AppConfig, env: dict[str, str]) -> None:
        replay_calls.append((config.config_path, env))

    def record_run(app: object, **kwargs: Any) -> None:
        run_calls.append(kwargs)

    monkeypatch.setattr(api_main, "replay_config_warnings", record_replay)
    monkeypatch.setattr(server, "replay_config_warnings", record_replay, raising=False)
    monkeypatch.setattr(server.uvicorn, "run", record_run)

    server.main()

    assert [path for path, _env in replay_calls] == [config_path]
    assert run_calls == [{"host": "127.0.0.1", "port": 8000, "log_config": None}]
