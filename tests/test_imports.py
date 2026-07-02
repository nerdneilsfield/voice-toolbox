from __future__ import annotations

import sys


def test_core_package_imports() -> None:
    import voice_toolbox

    assert voice_toolbox.__version__ == "0.1.0"


def test_provider_imports_do_not_import_optional_mlx_audio_dependency() -> None:
    sys.modules.pop("mlx_audio", None)

    import voice_toolbox.providers  # noqa: F401
    import voice_toolbox.providers.mlx_audio  # noqa: F401

    assert "mlx_audio" not in sys.modules
