from __future__ import annotations

import uvicorn

from voice_toolbox.config import load_app_config
from voice_toolbox_api.main import create_app


def main() -> None:
    config = load_app_config()
    app = create_app(config=config)
    uvicorn.run(
        app,
        host=config.api.host,
        port=config.api.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
