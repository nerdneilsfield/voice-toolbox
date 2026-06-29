from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from voice_toolbox.config_models import ChunkingMode
from voice_toolbox.models import TTSMode

TextFormat = Literal["plain", "markdown", "auto"]
TextSourceKind = Literal["inline", "file"]


class TextSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None
    text_format: TextFormat = "plain"
    source_kind: TextSourceKind = "inline"
    metadata: dict[str, object] = Field(default_factory=dict)


class TextChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    text: str
    char_count: int = Field(ge=0)


class TextChunkPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunks: list[TextChunk] = Field(default_factory=list)
    chunking_enabled: bool = False
    chunking_mode: ChunkingMode = "auto"
    max_chars: int
    max_chunks: int
    silence_ms: int = Field(default=0, ge=0)
    repeated_leading_audio_tags: bool = False

    def metadata(self) -> dict[str, object]:
        return {
            "chunking_enabled": self.chunking_enabled,
            "chunking_operation": "tts",
            "chunking_mode": self.chunking_mode,
            "chunking_strategy": "text",
            "chunking_chunk_count": len(self.chunks),
            "chunking_max_chars": self.max_chars,
            "chunking_silence_ms": self.silence_ms,
            "chunking_text_lengths": [chunk.char_count for chunk in self.chunks],
            "chunking_repeated_leading_audio_tags": self.repeated_leading_audio_tags,
        }


class TTSChunkingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: TTSMode
    text: str | None
    chunking_mode: ChunkingMode = "auto"
    max_chars: int = Field(gt=0)
    max_chunks: int = Field(gt=0)
    silence_ms: int = Field(default=0, ge=0)
    repeat_leading_audio_tags: bool = True
    optimize_text_preview: bool = False
