from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Protocol

from voice_toolbox.chunking.models import TextChunk, TextChunkPlan, TextSource, TTSChunkingRequest
from voice_toolbox.models import TTSMode

TextFormat = Literal["plain", "markdown", "auto"]
InferredTextFormat = Literal["plain", "markdown"]

TEXT_SUFFIX_FORMATS: dict[str, InferredTextFormat] = {
    ".txt": "plain",
    ".md": "markdown",
    ".markdown": "markdown",
}
TEXT_SUFFIX_MIME_TYPES = {
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/x-markdown", "application/octet-stream"},
    ".markdown": {"text/markdown", "text/x-markdown", "application/octet-stream"},
}
LEADING_AUDIO_TAG_PATTERN = re.compile(
    r"^((?:\([^)\n]{1,32}\)|（[^）\n]{1,32}）|\[[^\]\n]{1,32}\])(?:\s+|$))+"
)


class UploadLike(Protocol):
    filename: str | None
    content_type: str | None
    file: Any


class TextSourceError(ValueError):
    def __init__(self, detail: str, *, status_code: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def read_text_upload(upload: UploadLike, *, max_bytes: int) -> TextSource:
    suffix = _text_suffix(upload.filename)
    text_format = infer_text_format_from_upload(upload.filename, upload.content_type)
    contents = _read_limited(upload, max_bytes=max_bytes)
    if b"\x00" in contents:
        raise TextSourceError("text file contains NUL bytes")
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TextSourceError("text file must be valid UTF-8") from exc
    return TextSource(
        text=text,
        text_format=text_format,
        source_kind="file",
        metadata={
            "source_kind": "file",
            "uploaded_text_file_name_hash": _filename_hash(upload.filename),
            "uploaded_text_file_suffix": suffix,
            "uploaded_text_file_size_bytes": len(contents),
            "source_text_raw_char_count": len(text),
        },
    )


def resolve_text_source(
    *,
    text: str | None,
    text_file: UploadLike | None,
    text_format: TextFormat | None,
    max_text_file_bytes: int,
    mode: TTSMode | None = None,
    optimize_text_preview: bool = False,
) -> TextSource:
    has_inline_text = text is not None and text.strip() != ""
    if has_inline_text and text_file is not None:
        raise TextSourceError("text and text_file are mutually exclusive")
    if mode == TTSMode.DESIGN and optimize_text_preview and text_file is not None:
        raise TextSourceError("text_file is not allowed when optimize_text_preview is true")
    if text_file is not None:
        source = read_text_upload(text_file, max_bytes=max_text_file_bytes)
        if text_format is not None:
            return source.model_copy(update={"text_format": text_format})
        return source
    raw_text = text if text is not None else None
    return TextSource(
        text=raw_text,
        text_format=text_format or "plain",
        source_kind="inline",
        metadata={
            "source_kind": "inline",
            "source_text_raw_char_count": len(raw_text or ""),
        },
    )


def infer_text_format_from_upload(
    filename: str | None,
    content_type: str | None,
) -> InferredTextFormat:
    suffix = _text_suffix(filename)
    mime_type = _normalized_mime_type(content_type)
    if mime_type not in TEXT_SUFFIX_MIME_TYPES[suffix]:
        raise TextSourceError(f"text file MIME type {mime_type!r} does not match suffix {suffix!r}")
    return TEXT_SUFFIX_FORMATS[suffix]


def plan_tts_text_chunks(request: TTSChunkingRequest) -> TextChunkPlan:
    text = (request.text or "").strip()
    if request.mode == TTSMode.DESIGN:
        return _plan_design_text(request, text)
    if not text:
        raise ValueError("text is required")
    if request.chunking_mode == "off" and len(text) > request.max_chars:
        raise ValueError("text exceeds single-call limit")
    if request.chunking_mode == "auto" and len(text) <= request.max_chars:
        return _single_chunk_plan(request, text, chunking_enabled=False)

    chunks = _split_text(text, max_chars=request.max_chars)
    repeated = False
    if request.repeat_leading_audio_tags:
        chunks, repeated = _propagate_leading_audio_tag(chunks, max_chars=request.max_chars)
    if any(len(chunk) > request.max_chars for chunk in chunks):
        raise ValueError("chunk exceeds max_chars")
    if len(chunks) > request.max_chunks:
        raise ValueError("chunk count exceeds max_chunks")
    return _chunk_plan(
        request,
        chunks,
        chunking_enabled=request.chunking_mode == "force" or len(chunks) > 1,
        repeated_leading_audio_tags=repeated,
    )


def _plan_design_text(request: TTSChunkingRequest, text: str) -> TextChunkPlan:
    if request.chunking_mode == "force":
        raise ValueError("design mode does not support force chunking")
    if text and len(text) > request.max_chars:
        raise ValueError("voice design text exceeds single-call limit")
    if not text and request.optimize_text_preview:
        return _chunk_plan(request, [], chunking_enabled=False)
    return _single_chunk_plan(request, text, chunking_enabled=False)


def _single_chunk_plan(
    request: TTSChunkingRequest,
    text: str,
    *,
    chunking_enabled: bool,
) -> TextChunkPlan:
    chunks = [text] if text else []
    return _chunk_plan(request, chunks, chunking_enabled=chunking_enabled)


def _chunk_plan(
    request: TTSChunkingRequest,
    chunks: list[str],
    *,
    chunking_enabled: bool,
    repeated_leading_audio_tags: bool = False,
) -> TextChunkPlan:
    return TextChunkPlan(
        chunks=[
            TextChunk(index=index, text=chunk, char_count=len(chunk))
            for index, chunk in enumerate(chunks)
        ],
        chunking_enabled=chunking_enabled,
        chunking_mode=request.chunking_mode,
        max_chars=request.max_chars,
        max_chunks=request.max_chunks,
        silence_ms=request.silence_ms,
        repeated_leading_audio_tags=repeated_leading_audio_tags,
    )


def _split_text(text: str, *, max_chars: int) -> list[str]:
    paragraphs = _split_paragraphs(text)
    chunks: list[str] = []
    for paragraph in paragraphs:
        chunks.extend(_split_span(paragraph, max_chars=max_chars))
    return _pack(chunks, max_chars=max_chars, separator="\n\n")


def _split_span(span: str, *, max_chars: int) -> list[str]:
    stripped = span.strip()
    if not stripped:
        return []
    if len(stripped) <= max_chars:
        return [stripped]
    for splitter in (_split_sentences, _split_clauses):
        pieces = splitter(stripped)
        if len(pieces) <= 1:
            continue
        split_pieces: list[str] = []
        for piece in pieces:
            split_pieces.extend(_split_span(piece, max_chars=max_chars))
        return _pack(split_pieces, max_chars=max_chars, separator=" ")
    return _hard_split(stripped, max_chars=max_chars)


def _split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]


def _split_sentences(text: str) -> list[str]:
    pieces: list[str] = []
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        boundary = char in "。！？；"
        if char in ".!?;":
            boundary = index + 1 == len(text) or text[index + 1].isspace()
        if boundary:
            pieces.append(text[start : index + 1].strip())
            index += 1
            while index < len(text) and text[index].isspace():
                index += 1
            start = index
            continue
        index += 1
    tail = text[start:].strip()
    if tail:
        pieces.append(tail)
    return [piece for piece in pieces if piece]


def _split_clauses(text: str) -> list[str]:
    pieces: list[str] = []
    start = 0
    for index, char in enumerate(text):
        if char in "，,、:：":
            pieces.append(text[start : index + 1].strip())
            start = index + 1
            while start < len(text) and text[start].isspace():
                start += 1
    tail = text[start:].strip()
    if tail:
        pieces.append(tail)
    return [piece for piece in pieces if piece]


def _pack(pieces: list[str], *, max_chars: int, separator: str) -> list[str]:
    packed: list[str] = []
    current = ""
    for piece in pieces:
        if not piece:
            continue
        joiner = "" if not current else _separator_between(current, separator)
        candidate = piece if not current else f"{current}{joiner}{piece}"
        if current and len(candidate) > max_chars:
            packed.append(current)
            current = piece
        else:
            current = candidate
    if current:
        packed.append(current)
    return packed


def _separator_between(current: str, separator: str) -> str:
    if separator == " " and current[-1] in "。！？；、：，":
        return ""
    return separator


def _hard_split(text: str, *, max_chars: int) -> list[str]:
    chunks: list[str] = []
    for start in range(0, len(text), max_chars):
        chunk = text[start : start + max_chars].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def _propagate_leading_audio_tag(chunks: list[str], *, max_chars: int) -> tuple[list[str], bool]:
    if len(chunks) <= 1:
        return chunks, False
    match = LEADING_AUDIO_TAG_PATTERN.match(chunks[0])
    if match is None:
        return chunks, False
    prefix = match.group(0)
    available = max_chars - len(prefix)
    if available <= 0:
        raise ValueError("leading audio tag prefix exceeds max_chars")
    repeated = False
    propagated = [chunks[0]]
    for chunk in chunks[1:]:
        content = chunk[len(prefix) :] if chunk.startswith(prefix) else chunk
        if len(prefix) + len(content) <= max_chars:
            propagated.append(f"{prefix}{content}")
            repeated = repeated or not chunk.startswith(prefix)
            continue
        for part in _hard_split(content, max_chars=available):
            propagated.append(f"{prefix}{part}")
            repeated = True
    return propagated, repeated


def _read_limited(upload: UploadLike, *, max_bytes: int) -> bytes:
    reader = getattr(upload.file, "read", None)
    if reader is None:
        raise TextSourceError("text_file is not readable")
    contents = reader(max_bytes + 1)
    if not isinstance(contents, bytes):
        raise TextSourceError("text_file reader must return bytes")
    if len(contents) > max_bytes:
        raise TextSourceError("text file exceeds max_text_file_bytes", status_code=413)
    if not contents:
        raise TextSourceError("text file is empty")
    return contents


def _text_suffix(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in TEXT_SUFFIX_FORMATS:
        raise TextSourceError("unsupported text file suffix")
    return suffix


def _normalized_mime_type(content_type: str | None) -> str:
    mime_type = (content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    return mime_type or "application/octet-stream"


def _filename_hash(filename: str | None) -> str:
    basename = Path(filename or "upload.txt").name.encode("utf-8", errors="surrogatepass")
    return sha256(basename).hexdigest()[:12]
