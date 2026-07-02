from __future__ import annotations

import inspect
import io
import importlib
import platform
import tempfile
import threading
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import TracebackType
from typing import Any, Iterator
from uuid import uuid4

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.defaults import (
    MLX_AUDIO_MODEL_ALIASES,
    make_default_mlx_audio_provider_config,
)
from voice_toolbox.models import (
    ASRRequest,
    AudioArtifact,
    ModelInfo,
    OperationResult,
    OperationStatus,
    ProviderAudioResult,
    TranscriptArtifact,
    TTSMode,
    TTSRequest,
    VoiceInfo,
)
from voice_toolbox.providers.base import ProviderError, UnsupportedCapability
from voice_toolbox.providers.registry import ASR_CAPABILITY, TTS_MODE_CAPABILITIES
from voice_toolbox.transcripts import TranscriptPayload, TranscriptSegment

# Keep aligned with Blaizzy/mlx-audio `mlx_audio/utils.py`
# `DEFAULT_ALLOW_PATTERNS`, then append `*.onnx` only for BailingMM/Ming Omni loads.
DEFAULT_MLX_ALLOW_PATTERNS = [
    "*.json",
    "*.safetensors",
    "*.py",
    "*.model",
    "*.tiktoken",
    "*.txt",
    "*.jinja",
    "*.jsonl",
    "*.yaml",
    "*.npz",
    "*.pth",
]
BAILINGMM_MODEL_MARKERS = ("ming-omni", "bailingmm", "bailing-mm")
KOKORO_MODEL_MARKERS = ("kokoro",)
TTS_CORE_OPTION_KEYS = {"text", "voice", "ref_audio", "ref_text"}
ASR_CORE_OPTION_KEYS = {"audio", "language"}
FORCED_ALIGNER_MARKERS = ("forcedaligner", "forced-aligner", "qwen3-forcedaligner")

TTSLoader = Callable[..., Any]
STTLoader = Callable[..., Any]
WavWriter = Callable[[Any, int], bytes]
PlatformCheck = Callable[[], None]
TTSCacheKey = tuple[str, tuple[str, ...]]


def _load_tts_model(model_id: str, **kwargs: object) -> Any:
    try:
        module = importlib.import_module("mlx_audio.tts.utils")
    except ImportError as exc:
        raise _dependency_error(exc, selected_model=model_id, upstream_model=model_id) from exc
    load = getattr(module, "load")
    return load(model_id, **kwargs)


def _load_stt_model(model_id: str, **kwargs: object) -> Any:
    try:
        module = importlib.import_module("mlx_audio.stt")
    except ImportError as exc:
        raise _dependency_error(exc, selected_model=model_id, upstream_model=model_id) from exc
    load = getattr(module, "load")
    return load(model_id, **kwargs)


def _write_wav_bytes(audio: Any, sample_rate: int) -> bytes:
    try:
        module = importlib.import_module("mlx_audio.audio_io")
    except ImportError as exc:
        raise _dependency_error(exc, selected_model="audio_io", upstream_model="audio_io") from exc
    write = getattr(module, "write")
    buffer = io.BytesIO()
    write(buffer, audio, sample_rate, format="wav")
    return buffer.getvalue()


class MlxAudioProvider:
    def __init__(
        self,
        *,
        config: ConfiguredProvider | None = None,
        artifact_root: Path | str | None = None,
        artifact_store: ArtifactStore | None = None,
        tts_loader: TTSLoader = _load_tts_model,
        stt_loader: STTLoader = _load_stt_model,
        wav_writer: WavWriter = _write_wav_bytes,
        platform_check: PlatformCheck | None = None,
    ) -> None:
        self._config = config or make_default_mlx_audio_provider_config()
        self._default_models = self._config.default_models or ProviderDefaultModels()
        self._models_by_id = {model.id: model for model in self._config.models}
        self._operation_prefix = uuid4().hex
        self._operation_counter = 0
        self._closed = False
        self._active_operations = 0
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._lifecycle_lock = threading.RLock()
        self._lifecycle_condition = threading.Condition(self._lifecycle_lock)
        self._lease_state = threading.local()
        self._counter_lock = threading.Lock()
        self._tts_cache_lock = threading.Lock()
        self._stt_cache_lock = threading.Lock()
        self._tts_models: dict[TTSCacheKey, Any] = {}
        self._stt_models: dict[str, Any] = {}
        self._tts_inference_locks: dict[TTSCacheKey, threading.Lock] = {}
        self._stt_inference_locks: dict[str, threading.Lock] = {}
        self._tts_loader = tts_loader
        self._stt_loader = stt_loader
        self._wav_writer = wav_writer
        self._platform_check = platform_check or _ensure_apple_silicon_macos
        if artifact_store is not None:
            self._artifact_store = artifact_store
            self._artifact_root = artifact_store.root
        else:
            if artifact_root is None:
                self._temp_dir = tempfile.TemporaryDirectory()
                root = Path(self._temp_dir.name)
            else:
                root = Path(artifact_root)
            self._artifact_root = root
            self._artifact_store = ArtifactStore(root)
        self.id = self._config.id
        self.name = self._config.name

    def capabilities(self) -> set[str]:
        return {model.capability for model in self._config.models if model.capability is not None}

    def list_models(self) -> list[ModelInfo]:
        return [model.model_copy() for model in self._config.models]

    def list_voices(self) -> list[VoiceInfo]:
        return [voice.model_copy() for voice in self._config.voices]

    @property
    def artifact_root(self) -> Path:
        return self._artifact_root

    def close(self) -> None:
        if getattr(self._lease_state, "depth", 0) > 0:
            raise ProviderError("cannot close mlx_audio provider while operation is active")
        with self._lifecycle_condition:
            self._closed = True
            while self._active_operations > 0:
                self._lifecycle_condition.wait()
            if self._temp_dir is not None:
                self._temp_dir.cleanup()
                self._temp_dir = None

    def __enter__(self) -> MlxAudioProvider:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @contextmanager
    def _operation_lease(self) -> Iterator[None]:
        depth = getattr(self._lease_state, "depth", 0)
        if depth > 0:
            self._lease_state.depth = depth + 1
            try:
                yield
            finally:
                self._lease_state.depth = depth
            return

        with self._lifecycle_condition:
            if self._closed:
                raise ProviderError("mlx_audio provider is closed")
            self._active_operations += 1
        self._lease_state.depth = 1
        try:
            yield
        finally:
            self._lease_state.depth = 0
            with self._lifecycle_condition:
                self._active_operations -= 1
                if self._active_operations == 0:
                    self._lifecycle_condition.notify_all()

    def synthesize(
        self,
        request: TTSRequest,
        *,
        artifact_metadata: Mapping[str, object] | None = None,
    ) -> AudioArtifact:
        with self._operation_lease():
            return self._synthesize(request, artifact_metadata=artifact_metadata)

    def _synthesize(
        self,
        request: TTSRequest,
        *,
        artifact_metadata: Mapping[str, object] | None = None,
    ) -> AudioArtifact:
        operation_id = self._next_operation_id("tts")
        started_at = datetime.now(UTC)
        result = self.synthesize_bytes(request)
        metadata = {
            **dict(artifact_metadata or {}),
            "model": result.model,
            "operation": "tts",
            "output_format": request.output_format,
            "provider_id": self.id,
            "source_text_length": len(request.text or ""),
            "tts_mode": request.mode.value,
            "voice_id": request.voice_id,
        }
        if request.clone_reference_text:
            metadata["clone_reference_text_length"] = len(request.clone_reference_text)
        if request.mode == TTSMode.CLONE:
            if request.clone_sample_path is not None:
                metadata["uploaded_file_name_hash"] = _file_name_hash(request.clone_sample_path.name)
                metadata["uploaded_file_suffix"] = request.clone_sample_path.suffix
            metadata.update(
                {
                    "base64_size": request.clone_base64_size,
                    "consent_confirmed": request.consent_confirmed,
                    "raw_byte_size": request.clone_raw_byte_size,
                    "uploaded_file_mime_type": request.clone_mime_type,
                }
            )
        artifact = self._artifact_store.write_audio(
            operation_id=operation_id,
            provider_id=self.id,
            operation="tts",
            audio=result.audio,
            mime_type=result.mime_type,
            suffix=result.suffix,
            metadata=metadata,
        )
        self._artifact_store.record_operation(
            OperationResult(
                operation_id=operation_id,
                operation="tts",
                status=OperationStatus.COMPLETED,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                artifact_ids=[artifact.id],
            )
        )
        return artifact

    def synthesize_bytes(self, request: TTSRequest) -> ProviderAudioResult:
        with self._operation_lease():
            return self._synthesize_bytes(request)

    def _synthesize_bytes(self, request: TTSRequest) -> ProviderAudioResult:
        self._ensure_open()
        self._platform_check()
        if request.output_format != "wav":
            raise ProviderError("mlx_audio TTS output format must be wav")
        selected = self._resolve_tts_model(request)
        upstream = _upstream_model_id(selected)
        model, inference_lock = self._load_tts(selected, upstream)
        kwargs = self._tts_kwargs(request)
        kwargs = _validated_generate_kwargs(model.generate, kwargs)
        try:
            with inference_lock:
                results = list(model.generate(**kwargs))
                audio, sample_rate = _merge_generation_results(results, model)
                wav_audio = self._wav_writer(audio, sample_rate)
            return ProviderAudioResult(
                audio=wav_audio,
                mime_type="audio/wav",
                suffix=".wav",
                model=selected,
            )
        except ProviderError:
            raise
        except Exception as exc:
            request_language = kwargs.get("lang_code")
            raise _dependency_error(
                exc,
                selected_model=selected,
                upstream_model=upstream,
                request_language=str(request_language) if request_language is not None else None,
            ) from exc

    def transcribe(self, request: ASRRequest) -> TranscriptArtifact:
        with self._operation_lease():
            return self._transcribe(request)

    def _transcribe(self, request: ASRRequest) -> TranscriptArtifact:
        operation_id = self._next_operation_id("asr")
        started_at = datetime.now(UTC)
        payload = self.transcribe_payload(request)
        artifact = self._artifact_store.write_transcript(
            operation_id=operation_id,
            provider_id=self.id,
            operation="asr",
            text=payload.text,
            payload=payload,
            metadata={
                **request.artifact_metadata,
                "base64_size": request.base64_size,
                "language": request.language,
                "model": request.model or self._default_models.asr,
                "operation": "asr",
                "provider_id": self.id,
                "raw_byte_size": request.raw_byte_size,
                "uploaded_file_mime_type": request.mime_type,
                "uploaded_file_name_hash": _file_name_hash(request.audio_path.name),
                "uploaded_file_suffix": request.audio_path.suffix,
            },
        )
        self._artifact_store.record_operation(
            OperationResult(
                operation_id=operation_id,
                operation="asr",
                status=OperationStatus.COMPLETED,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                artifact_ids=[artifact.id],
            )
        )
        return artifact

    def transcribe_payload(self, request: ASRRequest) -> TranscriptPayload:
        with self._operation_lease():
            return self._transcribe_payload(request)

    def _transcribe_payload(self, request: ASRRequest) -> TranscriptPayload:
        self._ensure_open()
        self._platform_check()
        selected = self._resolve_asr_model(request)
        if _is_forced_aligner(selected):
            raise UnsupportedCapability(
                "mlx_audio forced alignment is not asr.transcribe; use a future alignment capability"
            )
        upstream = _upstream_model_id(selected)
        model, inference_lock = self._load_stt(selected, upstream)
        kwargs = _provider_options_without_core_collisions(
            request.provider_options,
            core_keys=ASR_CORE_OPTION_KEYS,
        )
        language = _asr_language(request.language)
        if language is not None:
            kwargs["language"] = language
        kwargs = _validated_generate_kwargs(model.generate, kwargs)
        try:
            with inference_lock:
                result = model.generate(str(request.audio_path), **kwargs)
        except ProviderError:
            raise
        except Exception as exc:
            raise _dependency_error(exc, selected_model=selected, upstream_model=upstream) from exc
        text = getattr(result, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("mlx_audio response is missing transcript text")
        return TranscriptPayload(text=text, segments=_segments_from_result(result))

    def _load_tts(self, selected: str, upstream: str) -> tuple[Any, threading.Lock]:
        cache_key, kwargs = _tts_cache_key(selected, upstream)
        with self._tts_cache_lock:
            if cache_key in self._tts_models:
                return self._tts_models[cache_key], self._tts_inference_locks[cache_key]
            try:
                self._tts_models[cache_key] = self._tts_loader(upstream, **kwargs)
                self._tts_inference_locks[cache_key] = threading.Lock()
            except ProviderError:
                raise
            except Exception as exc:
                raise _dependency_error(exc, selected_model=selected, upstream_model=upstream) from exc
            return self._tts_models[cache_key], self._tts_inference_locks[cache_key]

    def _load_stt(self, selected: str, upstream: str) -> tuple[Any, threading.Lock]:
        with self._stt_cache_lock:
            if upstream in self._stt_models:
                return self._stt_models[upstream], self._stt_inference_locks[upstream]
            try:
                self._stt_models[upstream] = self._stt_loader(upstream)
                self._stt_inference_locks[upstream] = threading.Lock()
            except ProviderError:
                raise
            except Exception as exc:
                raise _dependency_error(exc, selected_model=selected, upstream_model=upstream) from exc
            return self._stt_models[upstream], self._stt_inference_locks[upstream]

    def _resolve_tts_model(self, request: TTSRequest) -> str:
        if request.mode == TTSMode.DESIGN:
            raise UnsupportedCapability("mlx_audio provider does not support TTS mode: design")
        capability = TTS_MODE_CAPABILITIES[request.mode]
        model = request.model or self._default_tts_model(request.mode)
        self._validate_model_id(model, expected_capability=capability)
        if request.mode == TTSMode.CLONE and not request.clone_reference_text:
            raise ProviderError("mlx_audio clone mode requires clone_reference_text")
        return model

    def _resolve_asr_model(self, request: ASRRequest) -> str:
        model = request.model or self._default_models.asr
        if model is None:
            raise ProviderError(f"mlx_audio provider {self.id} has no default ASR model")
        if _is_forced_aligner(model):
            return model
        self._validate_model_id(model, expected_capability=ASR_CAPABILITY)
        return model

    def _default_tts_model(self, mode: TTSMode) -> str:
        default_by_mode = {
            TTSMode.BUILTIN: self._default_models.tts_builtin,
            TTSMode.DESIGN: self._default_models.tts_design,
            TTSMode.CLONE: self._default_models.tts_clone,
        }
        model = default_by_mode[mode]
        if model is None:
            raise ProviderError(f"mlx_audio provider {self.id} has no default TTS model for {mode}")
        return model

    def _validate_model_id(self, model: str, *, expected_capability: str) -> None:
        model_info = self._models_by_id.get(model)
        if model_info is None:
            raise ProviderError(f"unsupported MLX Audio model: {model}")
        if model_info.capability != expected_capability:
            raise ProviderError(f"unsupported MLX Audio model for {expected_capability}: {model}")

    def _tts_kwargs(self, request: TTSRequest) -> dict[str, object]:
        kwargs = _provider_options_without_core_collisions(
            request.provider_options,
            core_keys=TTS_CORE_OPTION_KEYS,
        )
        kwargs["text"] = request.text or ""
        if request.voice_id:
            kwargs["voice"] = request.voice_id
        if "lang_code" not in kwargs:
            kwargs["lang_code"] = "auto"
        if request.mode == TTSMode.CLONE:
            kwargs["ref_audio"] = str(request.clone_sample_path)
            kwargs["ref_text"] = request.clone_reference_text
        return kwargs

    def _next_operation_id(self, operation: str) -> str:
        with self._counter_lock:
            self._operation_counter += 1
            counter = self._operation_counter
        return f"{self.id}-{self._operation_prefix}-{operation}-{counter}"

    def _ensure_open(self) -> None:
        with self._lifecycle_condition:
            if self._closed and getattr(self._lease_state, "depth", 0) == 0:
                raise ProviderError("mlx_audio provider is closed")


def _ensure_apple_silicon_macos() -> None:
    if platform.system() != "Darwin" or platform.machine() not in {"arm64", "aarch64"}:
        raise ProviderError("mlx_audio provider requires Apple Silicon macOS")


def _upstream_model_id(model_id: str) -> str:
    return MLX_AUDIO_MODEL_ALIASES.get(model_id, model_id)


def _is_forced_aligner(model_id: str) -> bool:
    lowered = model_id.lower()
    return any(marker in lowered for marker in FORCED_ALIGNER_MARKERS)


def _is_bailingmm_model(selected_model: str, upstream_model: str) -> bool:
    lowered = f"{selected_model} {upstream_model}".lower()
    return any(marker in lowered for marker in BAILINGMM_MODEL_MARKERS)


def _is_kokoro_model(selected_model: str, upstream_model: str) -> bool:
    lowered = f"{selected_model} {upstream_model}".lower()
    return any(marker in lowered for marker in KOKORO_MODEL_MARKERS)


def _tts_cache_key(selected: str, upstream: str) -> tuple[TTSCacheKey, dict[str, object]]:
    allow_patterns: list[str] = []
    if _is_bailingmm_model(selected, upstream):
        allow_patterns = [*DEFAULT_MLX_ALLOW_PATTERNS, "*.onnx"]
    kwargs: dict[str, object] = {}
    if allow_patterns:
        kwargs["allow_patterns"] = allow_patterns
    return (upstream, tuple(allow_patterns)), kwargs


def _asr_language(language: str) -> str | None:
    return {"auto": None, "zh": "Chinese", "en": "English"}[language]


def _file_name_hash(filename: str) -> str:
    return sha256(filename.encode("utf-8")).hexdigest()[:12]


def _provider_options_without_core_collisions(
    options: Mapping[str, object],
    *,
    core_keys: set[str],
) -> dict[str, object]:
    collisions = sorted(set(options) & core_keys)
    if collisions:
        raise ProviderError(f"provider option {collisions[0]} collides with mlx_audio core argument")
    return dict(options)


def _validated_generate_kwargs(
    generate: Callable[..., object],
    kwargs: dict[str, object],
) -> dict[str, object]:
    try:
        signature = inspect.signature(generate)
    except (TypeError, ValueError):
        return kwargs
    parameters = signature.parameters.values()
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return kwargs
    allowed = {
        parameter.name
        for parameter in signature.parameters.values()
        if parameter.kind
        in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
    }
    unsupported = sorted(set(kwargs) - allowed)
    if unsupported:
        raise ProviderError(f"unsupported mlx_audio provider option: {unsupported[0]}")
    return kwargs


def _merge_generation_results(results: Iterable[Any], model: Any) -> tuple[Any, int]:
    result_list = list(results)
    if not result_list:
        raise ProviderError("mlx_audio generated no audio")
    chunks: list[float] = []
    sample_rate = getattr(model, "sample_rate", 24000)
    for result in result_list:
        audio = getattr(result, "audio", None)
        if audio is None:
            continue
        chunks.extend(_audio_values(audio))
        sample_rate = int(getattr(result, "sample_rate", sample_rate))
    if not chunks:
        raise ProviderError("mlx_audio generated no audio")
    return chunks, sample_rate


def _audio_values(audio: Any) -> list[float]:
    if hasattr(audio, "tolist"):
        audio = audio.tolist()
    if isinstance(audio, list):
        return [float(value) for value in audio]
    return [float(value) for value in audio]


def _segments_from_result(result: Any) -> list[TranscriptSegment]:
    segments = getattr(result, "segments", None) or []
    parsed: list[TranscriptSegment] = []
    for segment in segments:
        text = _segment_value(segment, "text")
        if not isinstance(text, str) or not text.strip():
            continue
        start = _segment_value(segment, "start")
        if start is None:
            start = _segment_value(segment, "start_time")
        end = _segment_value(segment, "end")
        if end is None:
            end = _segment_value(segment, "end_time")
        speaker = _segment_value(segment, "speaker")
        parsed.append(
            TranscriptSegment(
                text=text,
                start_seconds=float(start) if start is not None else None,
                end_seconds=float(end) if end is not None else None,
                speaker=speaker if isinstance(speaker, str) else None,
            )
        )
    return parsed


def _segment_value(segment: Any, key: str) -> Any:
    if isinstance(segment, Mapping):
        return segment.get(key)
    return getattr(segment, key, None)


def _dependency_error(
    exc: BaseException,
    *,
    selected_model: str,
    upstream_model: str,
    request_language: str | None = None,
) -> ProviderError:
    module = _missing_module(exc)
    text = str(exc) or exc.__class__.__name__
    hint = _install_hint(
        module,
        text,
        selected_model=selected_model,
        upstream_model=upstream_model,
        request_language=request_language,
    )
    if hint is None:
        if module is None:
            return ProviderError(
                f"mlx_audio model {selected_model} ({upstream_model}) failed: {text}"
            )
        return ProviderError(
            f"mlx_audio model {selected_model} ({upstream_model}) is missing a dependency: "
            f"{module}. Original error: {text}"
        )
    message = f"mlx_audio model {selected_model} ({upstream_model}) is missing a dependency"
    if module:
        message = f"{message}: {module}"
    if hint:
        message = f"{message}; {hint}"
    if text:
        message = f"{message}. Original error: {text}"
    return ProviderError(message)


def _missing_module(exc: BaseException) -> str | None:
    current: BaseException | None = exc
    while current is not None:
        name = getattr(current, "name", None)
        if isinstance(current, ModuleNotFoundError) and isinstance(name, str):
            return name
        if isinstance(current, ImportError) and isinstance(name, str):
            return name
        current = current.__cause__
    return None


def _install_hint(
    module: str | None,
    text: str,
    *,
    selected_model: str,
    upstream_model: str,
    request_language: str | None = None,
) -> str | None:
    lowered = text.lower()
    if module is not None and module.startswith("mlx_audio"):
        return "install voice-toolbox[mac]"
    if module == "misaki" or "misaki" in lowered:
        hint = "pip install misaki"
        if _is_kokoro_model(selected_model, upstream_model):
            language = (request_language or "").lower()
            if language in {"j", "ja", "japanese"}:
                hint = f"{hint}; Kokoro Japanese voices need pip install 'misaki[ja]'"
            elif language in {"z", "zh", "chinese", "mandarin"}:
                hint = f"{hint}; Kokoro Mandarin voices need pip install 'misaki[zh]'"
        return hint
    if module == "nagisa" or "nagisa" in lowered:
        return "pip install nagisa; needed by Qwen3 ForcedAligner Japanese alignment"
    if module == "soynlp" or "soynlp" in lowered:
        return "pip install soynlp; needed by Qwen3 ForcedAligner Korean alignment"
    if _is_bailingmm_model(selected_model, upstream_model) and (
        module in {"onnx", "safetensors"}
        or "campplus" in lowered
        or "onnx" in lowered
        or "safetensors" in lowered
    ):
        return "Ming Omni BailingMM campplus conversion may need pip install onnx safetensors"
    if module == "mistral_common" or "mistral-common" in lowered:
        return "install mlx-audio[tts] or voice-toolbox[mac]"
    return None
