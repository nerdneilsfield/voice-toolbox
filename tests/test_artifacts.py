import sqlite3

from voice_toolbox.artifacts import ArtifactStore, redact_metadata
from voice_toolbox.settings import has_mimo_api_key, load_settings
from voice_toolbox.storage import MetadataStore


def test_redact_metadata_excludes_api_key_and_data_url_and_maps_source_text_length() -> None:
    metadata = redact_metadata(
        {
            "api_key": "secret",
            "data_url": "data:audio/wav;base64,AAAA",
            "source_text": "hello",
            "provider_id": "mimo",
        }
    )

    assert "api_key" not in metadata
    assert "data_url" not in metadata
    assert metadata["source_text_length"] == 5
    assert metadata["provider_id"] == "mimo"


def test_redact_metadata_excludes_audio_payload_keys() -> None:
    metadata = redact_metadata(
        {
            "base64": "AAAA",
            "base64_payload": "BBBB",
            "data_url": "data:audio/wav;base64,CCCC",
            "raw_audio": b"audio",
            "audio_bytes": b"bytes",
            "api_key": "secret",
            "provider_id": "mimo",
        }
    )

    assert "base64" not in metadata
    assert "base64_payload" not in metadata
    assert "data_url" not in metadata
    assert "raw_audio" not in metadata
    assert "audio_bytes" not in metadata
    assert "api_key" not in metadata
    assert metadata["provider_id"] == "mimo"


def test_redact_metadata_drops_unknown_and_sensitive_like_keys() -> None:
    metadata = redact_metadata(
        {
            "Authorization": "Bearer secret",
            "api-key": "secret",
            "input_audio": "audio",
            "audio_metadata": {"duration": 1},
            "arbitrary_unknown": "keep me out",
            "base64_like": "AAAA",
            "provider_id": "mimo",
        }
    )

    assert metadata == {"provider_id": "mimo"}


def test_redact_metadata_preserves_allowed_direct_keys_and_text_lengths() -> None:
    metadata = redact_metadata(
        {
            "provider_id": "mimo",
            "model": "mimo-v2.5-asr",
            "operation": "tts",
            "tts_mode": "builtin",
            "output_format": "wav",
            "voice_id": "voice-1",
            "uploaded_file_name": "sample.wav",
            "uploaded_file_mime_type": "audio/wav",
            "raw_byte_size": 12,
            "base64_size": 16,
            "language": "auto",
            "consent_confirmed": True,
            "source_text": "hello",
            "style_instruction": "warm",
            "voice_description": "calm voice",
            "arbitrary_unknown": "drop",
        }
    )

    assert metadata == {
        "provider_id": "mimo",
        "model": "mimo-v2.5-asr",
        "operation": "tts",
        "tts_mode": "builtin",
        "output_format": "wav",
        "voice_id": "voice-1",
        "uploaded_file_name": "sample.wav",
        "uploaded_file_mime_type": "audio/wav",
        "raw_byte_size": 12,
        "base64_size": 16,
        "language": "auto",
        "consent_confirmed": True,
        "source_text_length": 5,
        "style_instruction_length": 4,
        "voice_description_length": 10,
    }


def test_redact_metadata_maps_prompt_fields_to_lengths() -> None:
    metadata = redact_metadata(
        {
            "style_instruction": "speak softly",
            "voice_description": "bright young voice",
        }
    )

    assert "style_instruction" not in metadata
    assert "voice_description" not in metadata
    assert metadata["style_instruction_length"] == 12
    assert metadata["voice_description_length"] == 18


def test_artifact_store_write_transcript_writes_text_and_json_sidecar(tmp_path) -> None:
    store = ArtifactStore(tmp_path)

    artifact = store.write_transcript(
        operation_id="op_123",
        provider_id="mimo",
        operation="asr",
        text="hello transcript",
        metadata={"api_key": "secret", "source_text": "abc"},
    )

    assert artifact.path.name == "op_123.txt"
    assert artifact.path.read_text(encoding="utf-8") == "hello transcript"
    assert artifact.mime_type == "text/plain; charset=utf-8"

    sidecar = artifact.path.with_suffix(".json")
    assert sidecar.exists()
    sidecar_text = sidecar.read_text(encoding="utf-8")
    assert '"id": "op_123"' in sidecar_text
    assert '"kind": "transcript"' in sidecar_text
    assert '"api_key"' not in sidecar_text
    assert '"source_text_length": 3' in sidecar_text


def test_metadata_store_creates_artifacts_and_operations_tables(tmp_path) -> None:
    db_path = tmp_path / "metadata.sqlite"
    store = MetadataStore(db_path)

    assert {"artifacts", "operations"}.issubset(store.table_names())

    with sqlite3.connect(db_path) as connection:
        operation_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(operations)").fetchall()
        }

    assert "started_at" in operation_columns
    assert "finished_at" in operation_columns


def test_load_settings_reads_mimo_base_url_from_env_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("MIMO_BASE_URL=https://example.test/v1\n", encoding="utf-8")

    settings = load_settings(env_path)

    assert settings.provider_id == "mimo"
    assert settings.base_url == "https://example.test/v1"
    assert settings.api_key_env == "MIMO_API_KEY"
    assert settings.default_output_format == "wav"


def test_has_mimo_api_key_detects_env_file_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("MIMO_API_KEY=secret\n", encoding="utf-8")

    assert has_mimo_api_key(env_path) is True
