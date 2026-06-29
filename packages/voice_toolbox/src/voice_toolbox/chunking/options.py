from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from voice_toolbox.models import (
    ProviderOptionOverride,
    ProviderOptionSpec,
)

MAX_PROVIDER_OPTION_BYTES = 4096
MAX_PROVIDER_OPTION_KEYS = 32


def parse_provider_options_json(raw: str | None) -> dict[str, object]:
    if raw is None or raw.strip() == "":
        return {}
    if len(raw.encode("utf-8")) > MAX_PROVIDER_OPTION_BYTES:
        raise ValueError("provider_options exceeds 4096 bytes")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("provider_options must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError("provider_options must be a JSON object")
    if not all(isinstance(key, str) for key in parsed):
        raise ValueError("provider_options must be a JSON object")
    _ensure_provider_options_limits(parsed)
    return dict(parsed)


def merge_provider_options(
    provider_options: Sequence[ProviderOptionSpec | Mapping[str, Any]],
    model_options: Sequence[
        ProviderOptionSpec | ProviderOptionOverride | Mapping[str, Any]
    ] = (),
    *,
    capability: str,
) -> list[ProviderOptionSpec]:
    merged: dict[str, ProviderOptionSpec] = {}
    order: list[str] = []
    disabled: set[str] = set()

    for raw in provider_options:
        option = _parse_provider_spec(raw)
        if option.capability != capability or not option.enabled:
            continue
        if option.key in merged:
            raise ValueError(f"duplicate provider option key: {option.key}")
        merged[option.key] = option
        order.append(option.key)

    for raw in model_options:
        override = _parse_model_override(raw)
        if override.capability != capability:
            continue
        if override.enabled is False:
            merged.pop(override.key, None)
            disabled.add(override.key)
            continue
        if override.key in disabled:
            continue
        if override.key in merged:
            merged[override.key] = _merge_option(merged[override.key], override)
            continue
        merged[override.key] = _spec_from_override(override)
        order.append(override.key)

    return [merged[key] for key in order if key in merged]


def validate_provider_options(
    provider_options: Mapping[str, object],
    specs: Sequence[ProviderOptionSpec],
    *,
    capability: str,
) -> dict[str, object]:
    _ensure_provider_options_limits(provider_options)
    by_key = {spec.key: spec for spec in specs if spec.enabled}
    all_by_key = {spec.key: spec for spec in specs}
    result: dict[str, object] = {}

    for key, value in provider_options.items():
        spec = by_key.get(key)
        if spec is None:
            if key in all_by_key:
                raise ValueError(f"provider option {key} does not belong to capability {capability}")
            raise ValueError(f"unknown provider option: {key}")
        if spec.capability != capability:
            raise ValueError(f"provider option {key} does not belong to capability {capability}")
        result[key] = _validate_value(key, value, spec)

    for spec in specs:
        if not spec.enabled or spec.capability != capability:
            continue
        if spec.key not in result and spec.default is not None:
            result[spec.key] = _validate_value(spec.key, spec.default, spec)
        if spec.required and spec.key not in result:
            raise ValueError(f"required provider option missing: {spec.key}")

    return dict(sorted(result.items()))


def build_provider_option_metadata(
    provider_options: Mapping[str, object],
    specs: Sequence[ProviderOptionSpec],
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "provider_option_keys": sorted(provider_options),
    }
    specs_by_key = {spec.key: spec for spec in specs}
    safe_values: dict[str, object] = {}
    for key, value in sorted(provider_options.items()):
        spec = specs_by_key.get(key)
        if spec is None or not spec.safe_metadata:
            continue
        if spec.type in {"boolean", "integer", "number"} and isinstance(
            value, bool | int | float
        ):
            safe_values[key] = value
        elif spec.type == "select" and isinstance(value, str) and len(value) <= 256:
            choice_values = {choice.value for choice in spec.choices}
            if value in choice_values:
                safe_values[key] = value
        elif spec.type == "multiselect" and isinstance(value, list):
            safe_values[f"{key}_count"] = len(value)
    if safe_values:
        metadata["provider_option_safe_values"] = safe_values
    return metadata


def normalize_provider_options(provider_options: Mapping[str, object]) -> tuple[tuple[str, Any], ...]:
    return tuple((key, _normalize_value(value)) for key, value in sorted(provider_options.items()))


def _parse_provider_spec(raw: ProviderOptionSpec | Mapping[str, Any]) -> ProviderOptionSpec:
    if isinstance(raw, ProviderOptionSpec):
        return raw
    return ProviderOptionSpec.model_validate(raw)


def _parse_model_override(
    raw: ProviderOptionSpec | ProviderOptionOverride | Mapping[str, Any],
) -> ProviderOptionOverride:
    if isinstance(raw, ProviderOptionOverride):
        return raw
    if isinstance(raw, ProviderOptionSpec):
        data = raw.model_dump(mode="python")
    else:
        data = dict(raw)
    return ProviderOptionOverride.model_validate(data)


def _merge_option(
    base: ProviderOptionSpec,
    override: ProviderOptionOverride,
) -> ProviderOptionSpec:
    data = base.model_dump(mode="python")
    for key, value in override.model_dump(mode="python", exclude_unset=True).items():
        if key in {"key", "capability"} or value is None:
            continue
        data[key] = value
    return ProviderOptionSpec.model_validate(data)


def _spec_from_override(override: ProviderOptionOverride) -> ProviderOptionSpec:
    try:
        return ProviderOptionSpec.model_validate(
            override.model_dump(mode="python", exclude_none=True)
        )
    except ValidationError as exc:
        raise ValueError(
            f"model provider option {override.key} must define full spec fields"
        ) from exc


def _ensure_provider_options_limits(provider_options: Mapping[str, object]) -> None:
    if len(provider_options) > MAX_PROVIDER_OPTION_KEYS:
        raise ValueError("provider_options has more than 32 keys")
    try:
        encoded = json.dumps(
            provider_options,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("provider_options must be JSON serializable") from exc
    if len(encoded) > MAX_PROVIDER_OPTION_BYTES:
        raise ValueError("provider_options exceeds 4096 bytes")


def _validate_value(key: str, value: object, spec: ProviderOptionSpec) -> object:
    if spec.type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"provider option {key} must be a boolean")
        return value
    if spec.type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"provider option {key} must be an integer")
        _validate_range(key, float(value), spec)
        return value
    if spec.type == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"provider option {key} must be a number")
        _validate_range(key, float(value), spec)
        return value
    if spec.type in {"string", "text"}:
        if not isinstance(value, str):
            raise ValueError(f"provider option {key} must be a string")
        return value
    if spec.type == "select":
        if not isinstance(value, str):
            raise ValueError(f"provider option {key} must be a string")
        choices = {choice.value for choice in spec.choices}
        if value not in choices:
            raise ValueError(f"provider option {key} must be one of configured choices")
        return value
    if spec.type == "multiselect":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"provider option {key} must be a list of strings")
        choices = {choice.value for choice in spec.choices}
        if any(item not in choices for item in value):
            raise ValueError(f"provider option {key} must be one of configured choices")
        return list(value)
    raise ValueError(f"provider option {key} has unsupported type: {spec.type}")


def _validate_range(key: str, value: float, spec: ProviderOptionSpec) -> None:
    if spec.min_value is not None and value < spec.min_value:
        raise ValueError(f"provider option {key} is outside allowed range")
    if spec.max_value is not None and value > spec.max_value:
        raise ValueError(f"provider option {key} is outside allowed range")


def _normalize_value(value: object) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, list):
        return tuple(_normalize_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(
            (str(item_key), _normalize_value(item_value))
            for item_key, item_value in sorted(value.items(), key=lambda item: str(item[0]))
        )
    return value
