from __future__ import annotations

import json
import re
import secrets
import shutil
from datetime import UTC, datetime, timedelta
from hashlib import sha1
from hashlib import sha256
from pathlib import Path, PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from voice_toolbox.audio_conversion import AudioConversionError, format_from_suffix
from voice_toolbox.chunking.options import normalize_provider_options
from voice_toolbox.models import ASRLanguage

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,96}$")


class ASRChunkSessionError(ValueError):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


class ASRChunkRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    path: str
    offset_ms: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    raw_byte_size: int = Field(ge=0)
    base64_size: int = Field(ge=0)
    mime_type: Literal["audio/wav"]
    suffix: Literal[".wav"]

    @property
    def end_ms(self) -> int:
        return self.offset_ms + self.duration_ms


class ASRChunkSessionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(pattern=SESSION_ID_PATTERN.pattern)
    created_at: datetime
    expires_at: datetime
    provider_id: str
    model: str | None = None
    language: ASRLanguage = "auto"
    total_chunks: int = Field(gt=0)
    source_duration_ms: int = Field(gt=0)
    source_file_name_hash: str | None = None
    source_file_suffix: str = ""
    transcript_timestamps: bool = False
    transcript_speakers: bool = False
    provider_options: dict[str, object] = Field(default_factory=dict, exclude=True)
    provider_options_hash: str | None = None
    option_metadata: dict[str, object] = Field(default_factory=dict)
    uploaded_bytes: int = Field(default=0, ge=0)
    max_upload_bytes: int = Field(gt=0)
    chunks: dict[int, ASRChunkRecord] = Field(default_factory=dict)


class ASRChunkSessionStore:
    def __init__(
        self,
        root: Path | str,
        *,
        ttl_seconds: int,
        max_upload_mb: int,
    ) -> None:
        self.root = Path(root)
        self.ttl_seconds = ttl_seconds
        self.max_upload_bytes = max_upload_mb * 1024 * 1024
        self._provider_options_by_session: dict[str, dict[str, object]] = {}
        self.session_root.mkdir(parents=True, exist_ok=True)
        self.session_root.chmod(0o700)

    @property
    def session_root(self) -> Path:
        return (self.root / "data" / "tmp" / "asr-chunk-sessions").resolve(strict=False)

    def create(
        self,
        *,
        provider_id: str,
        model: str | None,
        language: ASRLanguage,
        total_chunks: int,
        source_duration_ms: int,
        source_file_name: str | None,
        transcript_timestamps: bool,
        transcript_speakers: bool,
        provider_options: dict[str, object],
        option_metadata: dict[str, object],
        max_chunks: int,
        now: datetime | None = None,
    ) -> ASRChunkSessionMetadata:
        self.cleanup_expired(now=now)
        if total_chunks <= 0:
            raise ASRChunkSessionError("total_chunks must be greater than 0")
        if total_chunks > max_chunks:
            raise ASRChunkSessionError("total_chunks exceeds max_chunks")
        if source_duration_ms <= 0:
            raise ASRChunkSessionError("source_duration_ms must be greater than 0")
        created_at = now or datetime.now(UTC)
        session_id = generate_session_id()
        session_dir = self.session_dir(session_id)
        session_dir.mkdir(mode=0o700)
        self.chunk_dir(session_id).mkdir(mode=0o700)
        source_hash, source_suffix = _source_file_privacy_fields(source_file_name)
        metadata = ASRChunkSessionMetadata(
            session_id=session_id,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=self.ttl_seconds),
            provider_id=provider_id,
            model=model,
            language=language,
            total_chunks=total_chunks,
            source_duration_ms=source_duration_ms,
            source_file_name_hash=source_hash,
            source_file_suffix=source_suffix,
            transcript_timestamps=transcript_timestamps,
            transcript_speakers=transcript_speakers,
            provider_options={},
            provider_options_hash=provider_options_fingerprint(provider_options),
            option_metadata=dict(option_metadata),
            max_upload_bytes=self.max_upload_bytes,
        )
        self._provider_options_by_session[session_id] = dict(provider_options)
        self._write_metadata(metadata)
        return metadata.model_copy(update={"provider_options": dict(provider_options)})

    def load(
        self,
        session_id: str,
        *,
        now: datetime | None = None,
    ) -> ASRChunkSessionMetadata:
        self.cleanup_expired(now=now)
        self._validate_session_id(session_id)
        path = self.metadata_path(session_id)
        if not path.is_file():
            raise ASRChunkSessionError("chunk session not found", status_code=404)
        try:
            metadata = ASRChunkSessionMetadata.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            raise ASRChunkSessionError("chunk session metadata is invalid") from exc
        return metadata.model_copy(
            update={"provider_options": dict(self._provider_options_by_session.get(session_id, {}))}
        )

    def write_chunk(
        self,
        session_id: str,
        *,
        chunk_index: int,
        data: bytes,
        offset_ms: int,
        duration_ms: int,
        mime_type: Literal["audio/wav"],
        suffix: Literal[".wav"],
        max_raw_bytes: int | None = None,
        max_base64_bytes: int | None = None,
        now: datetime | None = None,
    ) -> ASRChunkSessionMetadata:
        metadata = self.load(session_id, now=now)
        if chunk_index < 0 or chunk_index >= metadata.total_chunks:
            raise ASRChunkSessionError("chunk_index out of bounds")
        if chunk_index in metadata.chunks:
            raise ASRChunkSessionError("duplicate chunk_index", status_code=409)
        if not data:
            raise ASRChunkSessionError("chunk file is empty")
        base64_size = _base64_size(len(data))
        if (max_raw_bytes is not None and len(data) > max_raw_bytes) or (
            max_base64_bytes is not None and base64_size > max_base64_bytes
        ):
            raise ASRChunkSessionError(
                "audio chunk exceeds provider payload limit",
                status_code=413,
            )
        if metadata.uploaded_bytes + len(data) > metadata.max_upload_bytes:
            raise ASRChunkSessionError("session upload quota exceeded", status_code=413)
        self._validate_chunk_timing(
            metadata,
            chunk_index=chunk_index,
            offset_ms=offset_ms,
            duration_ms=duration_ms,
        )
        chunk_path = self.chunk_path(session_id, chunk_index)
        with chunk_path.open("xb") as chunk_file:
            chunk_file.write(data)
        chunk_path.chmod(0o600)
        metadata.chunks[chunk_index] = ASRChunkRecord(
            index=chunk_index,
            path=str(chunk_path.relative_to(self.session_dir(session_id))),
            offset_ms=offset_ms,
            duration_ms=duration_ms,
            raw_byte_size=len(data),
            base64_size=base64_size,
            mime_type=mime_type,
            suffix=suffix,
        )
        metadata.uploaded_bytes += len(data)
        self._write_metadata(metadata)
        return metadata

    def finish_chunks(self, session_id: str) -> list[ASRChunkRecord]:
        metadata = self.load(session_id)
        if len(metadata.chunks) != metadata.total_chunks:
            raise ASRChunkSessionError("missing chunks")
        chunks = [metadata.chunks[index] for index in range(metadata.total_chunks)]
        tolerance_ms = 1500
        covered_end = 0
        for chunk in chunks:
            if chunk.offset_ms > covered_end + tolerance_ms:
                raise ASRChunkSessionError("source_duration_ms coverage gap")
            covered_end = max(covered_end, chunk.end_ms)
        if abs(covered_end - metadata.source_duration_ms) > tolerance_ms:
            raise ASRChunkSessionError("source_duration_ms coverage gap")
        return chunks

    def delete(self, session_id: str) -> bool:
        self.cleanup_expired()
        self._validate_session_id(session_id)
        path = self.session_dir(session_id)
        if not path.exists():
            return False
        shutil.rmtree(path)
        self._provider_options_by_session.pop(session_id, None)
        return True

    def cleanup_expired(self, *, now: datetime | None = None) -> None:
        current_time = now or datetime.now(UTC)
        if not self.session_root.exists():
            return
        for session_dir in self.session_root.iterdir():
            if not session_dir.is_dir():
                continue
            metadata_path = session_dir / "metadata.json"
            try:
                metadata = ASRChunkSessionMetadata.model_validate_json(
                    metadata_path.read_text(encoding="utf-8")
                )
            except (OSError, ValidationError, json.JSONDecodeError):
                continue
            expires_at = metadata.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= current_time:
                shutil.rmtree(session_dir, ignore_errors=True)
                self._provider_options_by_session.pop(metadata.session_id, None)

    def session_dir(self, session_id: str) -> Path:
        self._validate_session_id(session_id)
        return self.session_root / session_id

    def chunk_dir(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "chunks"

    def chunk_path(self, session_id: str, chunk_index: int) -> Path:
        return self.chunk_dir(session_id) / f"chunk-{chunk_index:04d}.wav"

    def metadata_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "metadata.json"

    def _write_metadata(self, metadata: ASRChunkSessionMetadata) -> None:
        path = self.metadata_path(metadata.session_id)
        path.write_text(
            json.dumps(
                metadata.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        path.chmod(0o600)

    def _validate_session_id(self, session_id: str) -> None:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise ASRChunkSessionError("chunk session not found", status_code=404)

    def _validate_chunk_timing(
        self,
        metadata: ASRChunkSessionMetadata,
        *,
        chunk_index: int,
        offset_ms: int,
        duration_ms: int,
    ) -> None:
        if offset_ms < 0:
            raise ASRChunkSessionError("offset_ms must be greater than or equal to 0")
        if duration_ms <= 0:
            raise ASRChunkSessionError("duration_ms must be greater than 0")
        if offset_ms + duration_ms > metadata.source_duration_ms + 1500:
            raise ASRChunkSessionError("chunk timing exceeds source_duration_ms")
        for existing in metadata.chunks.values():
            if existing.index < chunk_index and offset_ms <= existing.offset_ms:
                raise ASRChunkSessionError("chunk offset is non-monotonic")
            if existing.index > chunk_index and offset_ms >= existing.offset_ms:
                raise ASRChunkSessionError("chunk offset is non-monotonic")


def generate_session_id() -> str:
    return secrets.token_urlsafe(32)


def provider_options_fingerprint(provider_options: dict[str, object]) -> str | None:
    if not provider_options:
        return None
    encoded = json.dumps(
        normalize_provider_options(provider_options),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _source_file_privacy_fields(filename: str | None) -> tuple[str | None, str]:
    if not filename:
        return None, ""
    if "\x00" in filename or "/" in filename or "\\" in filename:
        raise ASRChunkSessionError("source_file_name must be a plain filename")
    if PureWindowsPath(filename).drive:
        raise ASRChunkSessionError("source_file_name must be a plain filename")
    raw_path = Path(filename)
    if raw_path.is_absolute() or raw_path.name != filename:
        raise ASRChunkSessionError("source_file_name must be a plain filename")
    basename = Path(filename).name
    digest = sha1(basename.encode("utf-8")).hexdigest()
    suffix = Path(basename).suffix.lower()
    if not suffix:
        return digest, ""
    try:
        format_from_suffix(suffix)
    except AudioConversionError:
        return digest, ""
    return digest, suffix


def _base64_size(raw_byte_size: int) -> int:
    return ((raw_byte_size + 2) // 3) * 4
