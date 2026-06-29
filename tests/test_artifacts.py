from datetime import UTC, datetime
import os
import stat
import sqlite3

import pytest

from voice_toolbox.artifacts import ArtifactStore, redact_metadata
from voice_toolbox.models import AudioArtifact, OperationResult, OperationStatus
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
            "uploaded_file_name_hash": "abcdef123456",
            "uploaded_file_suffix": ".wav",
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
        "uploaded_file_name_hash": "abcdef123456",
        "uploaded_file_suffix": ".wav",
        "uploaded_file_mime_type": "audio/wav",
        "raw_byte_size": 12,
        "base64_size": 16,
        "language": "auto",
        "consent_confirmed": True,
        "source_text_length": 5,
        "style_instruction_length": 4,
        "voice_description_length": 10,
    }


def test_redact_metadata_preserves_normalization_metadata_without_raw_text() -> None:
    metadata = redact_metadata(
        {
            "normalization_normalizer_id": "markdown_basic",
            "normalization_input_format": "markdown",
            "normalization_output_format": "plain",
            "normalization_changed": True,
            "normalization_input_length": 22,
            "normalization_output_length": 17,
            "normalization_ignored_options": ["preserve_unknown"],
            "source_text": "# Secret",
            "raw_text": "# Secret",
            "normalized_text": "Secret",
        }
    )

    assert metadata == {
        "normalization_normalizer_id": "markdown_basic",
        "normalization_input_format": "markdown",
        "normalization_output_format": "plain",
        "normalization_changed": True,
        "normalization_input_length": 22,
        "normalization_output_length": 17,
        "normalization_ignored_options": ["preserve_unknown"],
        "source_text_length": 8,
    }


def test_redact_metadata_preserves_provider_chunking_source_and_transcript_metadata() -> None:
    metadata = redact_metadata(
        {
            "provider_options": {"prompt": "secret"},
            "provider_option_keys": ["format", "prompt"],
            "provider_option_safe_values": {"format": "mp3", "speed": 1.1},
            "source_kind": "file",
            "uploaded_text_file_name_hash": "abcdef123456",
            "uploaded_text_file_suffix": ".md",
            "uploaded_text_file_size_bytes": 42,
            "source_text_raw_char_count": 40,
            "source_file_name_hash": "123456abcdef",
            "source_file_suffix": ".wav",
            "chunking_enabled": True,
            "chunking_operation": "tts",
            "chunking_mode": "auto",
            "chunking_strategy": "text",
            "chunking_chunk_count": 2,
            "chunking_max_chars": 1000,
            "chunking_silence_ms": 120,
            "chunking_text_lengths": [900, 200],
            "chunking_repeated_leading_audio_tags": True,
            "chunking_target_seconds": 90,
            "chunking_overlap_ms": 1200,
            "chunking_audio_durations_ms": [90000, 45000],
            "chunking_transcript_lengths": [100, 80],
            "chunking_dedupe_removed_chars": 12,
            "transcript_has_timestamps": True,
            "transcript_has_speakers": False,
            "transcript_segment_count": 3,
            "transcript_download_formats": ["txt", "srt"],
        }
    )

    assert "provider_options" not in metadata
    assert metadata["provider_option_keys"] == ["format", "prompt"]
    assert metadata["provider_option_safe_values"] == {"format": "mp3", "speed": 1.1}
    assert metadata["source_kind"] == "file"
    assert metadata["uploaded_text_file_name_hash"] == "abcdef123456"
    assert metadata["chunking_chunk_count"] == 2
    assert metadata["chunking_text_lengths"] == [900, 200]
    assert metadata["transcript_has_timestamps"] is True
    assert metadata["transcript_download_formats"] == ["txt", "srt"]


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


def test_redact_metadata_handles_non_string_text_fields() -> None:
    metadata = redact_metadata({"source_text": 12345})

    assert metadata == {"source_text_length": 5}


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
    assert '"path"' not in sidecar_text
    assert '"api_key"' not in sidecar_text
    assert '"source_text_length": 3' in sidecar_text
    assert stat.S_IMODE(artifact.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600
    assert stat.S_IMODE(sidecar.parent.stat().st_mode) == 0o700


def test_artifact_store_write_transcript_duplicate_id_preserves_original(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    first = store.write_transcript(
        operation_id="op_123",
        provider_id="mimo",
        operation="asr",
        text="original transcript",
        metadata={"source_text": "abc"},
    )
    original_sidecar = first.path.with_suffix(".json").read_text(encoding="utf-8")

    with pytest.raises(FileExistsError):
        store.write_transcript(
            operation_id="op_123",
            provider_id="mimo",
            operation="asr",
            text="replacement transcript",
            metadata={"source_text": "abcdef"},
        )

    assert first.path.read_text(encoding="utf-8") == "original transcript"
    assert first.path.with_suffix(".json").read_text(encoding="utf-8") == original_sidecar


def test_artifact_store_write_audio_duplicate_id_preserves_original(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    first = store.write_audio(
        operation_id="op_123",
        provider_id="mimo",
        operation="tts",
        audio=b"original audio",
        metadata={"provider_id": "mimo"},
    )
    original_sidecar = first.path.with_suffix(".json").read_text(encoding="utf-8")

    with pytest.raises(FileExistsError):
        store.write_audio(
            operation_id="op_123",
            provider_id="mimo",
            operation="tts",
            audio=b"replacement audio",
            metadata={"provider_id": "mimo"},
        )

    assert first.path.read_bytes() == b"original audio"
    assert first.path.with_suffix(".json").read_text(encoding="utf-8") == original_sidecar


def test_artifact_store_write_audio_supports_mp3(tmp_path) -> None:
    store = ArtifactStore(tmp_path)

    artifact = store.write_audio(
        operation_id="op_mp3",
        provider_id="openrouter",
        operation="tts",
        audio=b"mp3 audio",
        mime_type="audio/mpeg",
        suffix=".mp3",
        metadata={"output_format": "mp3"},
    )

    assert artifact.path.name == "op_mp3.mp3"
    assert artifact.path.read_bytes() == b"mp3 audio"
    assert artifact.mime_type == "audio/mpeg"
    assert '"mime_type": "audio/mpeg"' in artifact.path.with_suffix(".json").read_text(
        encoding="utf-8"
    )


def test_artifact_store_rejects_unsafe_operation_id_without_escape_file(tmp_path) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(ValueError):
        store.write_transcript(
            operation_id="../evil",
            provider_id="mimo",
            operation="asr",
            text="hello",
        )

    assert not (tmp_path / "data" / "evil.txt").exists()
    assert not (tmp_path / "evil.txt").exists()


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
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(db_path.parent.stat().st_mode) == 0o700


def test_metadata_store_inserts_artifact_and_rejects_duplicate_id(tmp_path) -> None:
    store = MetadataStore(tmp_path / "metadata.sqlite")
    artifact = AudioArtifact(
        id="op_123",
        provider_id="mimo",
        operation="tts",
        path=tmp_path / "op_123.wav",
        mime_type="audio/wav",
        metadata={"provider_id": "mimo"},
    )

    store.insert_artifact(artifact)

    row = store.connection.execute(
        "SELECT id, kind, provider_id, operation, mime_type, metadata FROM artifacts"
    ).fetchone()
    assert row == (
        "op_123",
        "audio",
        "mimo",
        "tts",
        "audio/wav",
        '{"provider_id": "mimo"}',
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_artifact(artifact)


def test_artifact_store_persists_artifact_metadata_to_sqlite(tmp_path) -> None:
    store = ArtifactStore(tmp_path)

    artifact = store.write_audio(
        operation_id="op_123",
        provider_id="mimo",
        operation="tts",
        audio=b"audio",
        metadata={"source_text": "hello"},
    )

    with sqlite3.connect(tmp_path / "data" / "voice_toolbox.sqlite") as connection:
        row = connection.execute(
            "SELECT id, kind, provider_id, operation, mime_type, metadata FROM artifacts"
        ).fetchone()

    assert row == (
        artifact.id,
        "audio",
        "mimo",
        "tts",
        "audio/wav",
        '{"source_text_length": 5}',
    )


def test_metadata_store_inserts_operation_and_rejects_duplicate_id(tmp_path) -> None:
    store = MetadataStore(tmp_path / "metadata.sqlite")
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    finished_at = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
    operation = OperationResult(
        operation_id="op_123",
        operation="tts",
        status=OperationStatus.COMPLETED,
        started_at=started_at,
        finished_at=finished_at,
        artifact_ids=["op_123"],
    )

    store.insert_operation(operation)

    row = store.connection.execute(
        "SELECT operation_id, operation, status, started_at, finished_at, artifact_ids "
        "FROM operations"
    ).fetchone()
    assert row == (
        "op_123",
        "tts",
        "completed",
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:01Z",
        '["op_123"]',
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_operation(operation)


def test_load_settings_reads_mimo_base_url_from_env_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("MIMO_BASE_URL=https://example.test/v1\n", encoding="utf-8")

    settings = load_settings(env_path)

    assert settings.provider_id == "mimo"
    assert settings.base_url == "https://example.test/v1"
    assert settings.api_key_env == "MIMO_API_KEY"
    assert settings.default_output_format == "wav"
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000
    assert "MIMO_BASE_URL" not in os.environ


def test_load_settings_reads_default_cwd_env_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "MIMO_BASE_URL=https://cwd-env.test/v1\n"
        "MIMO_API_KEY=secret\n"
        "API_HOST=127.0.0.2\n"
        "API_PORT=9000\n",
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings.base_url == "https://cwd-env.test/v1"
    assert settings.api_host == "127.0.0.2"
    assert settings.api_port == 9000
    assert has_mimo_api_key() is True
    assert "MIMO_API_KEY" not in os.environ


def test_has_mimo_api_key_detects_env_file_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("MIMO_API_KEY=secret\n", encoding="utf-8")

    assert has_mimo_api_key(env_path) is True
