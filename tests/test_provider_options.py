from __future__ import annotations

import pytest
from pydantic import ValidationError

from voice_toolbox.chunking.options import (
    build_provider_option_metadata,
    merge_provider_options,
    normalize_provider_options,
    parse_provider_options_json,
    validate_provider_options,
)
from voice_toolbox.models import ProviderOptionOverride, ProviderOptionSpec


def _spec(**overrides: object) -> ProviderOptionSpec:
    data: dict[str, object] = {
        "key": "speed",
        "label": "Speed",
        "type": "number",
        "capability": "tts.builtin",
    }
    data.update(overrides)
    return ProviderOptionSpec.model_validate(data)


def test_option_key_regex_and_shared_field_collisions_rejected() -> None:
    invalid_keys = ["Speed", "_speed", "speed-name", "s" * 65, "text", "voice_id"]

    for key in invalid_keys:
        with pytest.raises(ValidationError):
            _spec(key=key)


def test_select_and_multiselect_require_choices_and_validate_defaults() -> None:
    with pytest.raises(ValidationError, match="choices"):
        _spec(type="select", default="fast")

    with pytest.raises(ValidationError, match="default"):
        _spec(
            type="select",
            choices=[{"value": "normal", "label": "Normal"}],
            default="fast",
        )

    with pytest.raises(ValidationError, match="choices"):
        _spec(type="multiselect", default=["fast"])

    with pytest.raises(ValidationError, match="default"):
        _spec(
            type="multiselect",
            choices=[{"value": "normal", "label": "Normal"}],
            default=["fast"],
        )


def test_numeric_default_must_be_inside_bounds() -> None:
    with pytest.raises(ValidationError, match="default"):
        _spec(type="integer", default=11, min_value=1, max_value=10)

    with pytest.raises(ValidationError, match="default"):
        _spec(type="number", default=0.25, min_value=0.5, max_value=2.0)


def test_required_option_cannot_have_default() -> None:
    with pytest.raises(ValidationError, match="required"):
        _spec(required=True, default=1.0)


def test_model_override_merges_only_explicit_fields() -> None:
    provider = _spec(
        label="Speed",
        description="Speaking speed",
        default=1.0,
        min_value=0.5,
        max_value=2.0,
        step=0.1,
    )
    model_override = ProviderOptionOverride.model_validate(
        {"key": "speed", "capability": "tts.builtin", "max_value": 1.5}
    )

    merged = merge_provider_options(
        [provider],
        [model_override],
        capability="tts.builtin",
    )

    assert len(merged) == 1
    assert merged[0].label == "Speed"
    assert merged[0].description == "Speaking speed"
    assert merged[0].default == 1.0
    assert merged[0].min_value == 0.5
    assert merged[0].max_value == 1.5
    assert merged[0].step == 0.1


def test_model_partial_overrides_parse_without_full_spec_fields() -> None:
    override = ProviderOptionOverride.model_validate(
        {"key": "speed", "capability": "tts.builtin", "max_value": 1.5}
    )

    assert override.label is None
    assert override.type is None


def test_model_enabled_false_removes_inherited_option() -> None:
    provider = _spec(required=True)
    disabled = ProviderOptionOverride.model_validate(
        {"key": "speed", "capability": "tts.builtin", "enabled": False}
    )

    merged = merge_provider_options([provider], [disabled], capability="tts.builtin")

    assert merged == []
    with pytest.raises(ValueError, match="unknown provider option"):
        validate_provider_options({"speed": 1.0}, merged, capability="tts.builtin")


def test_model_enabled_false_rejects_extra_explicit_fields() -> None:
    with pytest.raises(ValidationError, match="enabled=false"):
        ProviderOptionOverride.model_validate(
            {
                "key": "speed",
                "capability": "tts.builtin",
                "enabled": False,
                "label": "Nope",
            }
        )


def test_provider_options_json_parse_limits_shape_and_size() -> None:
    assert parse_provider_options_json(None) == {}
    assert parse_provider_options_json('{"speed": 1}') == {"speed": 1}

    with pytest.raises(ValueError, match="provider_options must be a JSON object"):
        parse_provider_options_json("[1, 2]")

    with pytest.raises(ValueError, match="provider_options must be a JSON object"):
        parse_provider_options_json("{bad json")

    with pytest.raises(ValueError, match="provider_options exceeds 4096 bytes"):
        parse_provider_options_json('{"prompt": "' + ("x" * 4097) + '"}')

    too_many = "{" + ",".join(f'"k{i}": {i}' for i in range(33)) + "}"
    with pytest.raises(ValueError, match="provider_options has more than 32 keys"):
        parse_provider_options_json(too_many)


def test_validate_provider_options_applies_defaults_and_safe_metadata() -> None:
    specs = [
        _spec(default=1.0, min_value=0.5, max_value=2.0, safe_metadata=True),
        _spec(
            key="format",
            label="Format",
            type="select",
            choices=[{"value": "wav", "label": "WAV"}, {"value": "mp3", "label": "MP3"}],
            default="wav",
            safe_metadata=True,
        ),
        _spec(key="prompt", label="Prompt", type="string", safe_metadata=True),
        _spec(
            key="tags",
            label="Tags",
            type="multiselect",
            choices=[{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
            safe_metadata=True,
        ),
    ]

    validated = validate_provider_options(
        {"format": "mp3", "prompt": "secret", "tags": ["a", "b"]},
        specs,
        capability="tts.builtin",
    )
    metadata = build_provider_option_metadata(validated, specs)

    assert validated == {
        "speed": 1.0,
        "format": "mp3",
        "prompt": "secret",
        "tags": ["a", "b"],
    }
    assert metadata == {
        "provider_option_keys": ["format", "prompt", "speed", "tags"],
        "provider_option_safe_values": {
            "format": "mp3",
            "speed": 1.0,
            "tags_count": 2,
        },
    }


def test_validate_provider_options_rejects_unknown_wrong_capability_and_bad_values() -> None:
    specs = [
        _spec(required=True, min_value=0.5, max_value=2.0),
        _spec(key="name", label="Name", type="string"),
        _spec(
            key="quality",
            label="Quality",
            type="select",
            choices=[{"value": "high", "label": "High"}],
        ),
    ]

    with pytest.raises(ValueError, match="required provider option"):
        validate_provider_options({}, specs, capability="tts.builtin")

    with pytest.raises(ValueError, match="unknown provider option"):
        validate_provider_options({"other": True, "speed": 1.0}, specs, capability="tts.builtin")

    with pytest.raises(ValueError, match="outside allowed range"):
        validate_provider_options({"speed": 3.0}, specs, capability="tts.builtin")

    with pytest.raises(ValueError, match="must be a string"):
        validate_provider_options({"speed": 1.0, "name": 3}, specs, capability="tts.builtin")

    with pytest.raises(ValueError, match="must be one of"):
        validate_provider_options(
            {"speed": 1.0, "quality": "low"},
            specs,
            capability="tts.builtin",
        )

    asr_specs = [_spec(capability="asr.transcribe")]
    with pytest.raises(ValueError, match="does not belong to capability"):
        validate_provider_options({"speed": 1.0}, asr_specs, capability="tts.builtin")


def test_normalized_provider_options_compare_sorted_keys_and_numeric_equality() -> None:
    assert normalize_provider_options({"b": 2.0, "a": 1}) == normalize_provider_options(
        {"a": 1.0, "b": 2}
    )
