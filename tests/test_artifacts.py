import sqlite3

from voice_toolbox.artifacts import ArtifactStore, redact_metadata
from voice_toolbox.storage import MetadataStore


def test_redact_metadata_excludes_api_key_and_data_url_and_maps_source_text_length() -> None:
    metadata = redact_metadata(
        {
            "api_key": "secret",
            "data_url": "data:audio/wav;base64,AAAA",
            "source_text": "hello",
            "provider": "mimo",
        }
    )

    assert "api_key" not in metadata
    assert "data_url" not in metadata
    assert metadata["source_text_length"] == 5
    assert metadata["provider"] == "mimo"


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
