from __future__ import annotations

import uvicorn

from voice_toolbox.config import load_app_config, load_env_values
from voice_toolbox_api.main import create_app


def main() -> None:
    env_values = load_env_values()
    config = load_app_config(env_values=env_values, emit_warnings=False)
    app = create_app(config=config, env_values=env_values)
    uvicorn.run(
        app,
        host=config.api.host,
        port=config.api.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
