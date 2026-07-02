# MLX Audio Provider Design

## Goal

Add a local Apple Silicon provider backed by
[`Blaizzy/mlx-audio`](https://github.com/Blaizzy/mlx-audio) for the first useful
TTS and ASR workflows:

- `tts.builtin`
- `tts.clone`
- `asr.transcribe`

The first version deliberately excludes `tts.design`, STS, VAD, diarization, and
the `mlx_audio.server` wrapper.

## Dependency Model

`mlx-audio` is macOS/Apple Silicon specific and must not install with the normal
runtime or dev dependencies.

Add a separate project extra named `mac`:

```toml
[project.optional-dependencies]
mac = [
  "mlx-audio[tts,stt]>=0.4.4 ; sys_platform == 'darwin' and platform_machine == 'arm64'",
]
```

Users install it explicitly:

```bash
rtk uv sync --extra mac
pip install "voice-toolbox[mac]"
```

`dev` remains test/lint-only. It does not imply `mac`.

`mac` is the baseline Apple Silicon install. It deliberately stays close to
upstream `mlx-audio[tts,stt]`; model-specific extras are handled by model notes,
docs, and runtime install hints rather than being pulled into every Mac install.

Upstream `mlx-audio` keeps model-specific text dependencies out of its shared
extras, including `tts` and `all`. Mirror that policy so `voice-toolbox[mac]`
does not install dependencies for models the user may never run.

## Model-Specific Dependencies

Research against `Blaizzy/mlx-audio` main as of 2026-07-02 found these extra
dependency cases beyond `mlx-audio[tts,stt]`:

- Kokoro TTS needs `misaki` for text processing. Japanese voices may need
  `misaki[ja]`; Mandarin voices may need `misaki[zh]`. Kokoro is not in the
  initial built-in model list, but user-configured Kokoro models should surface
  this hint when `misaki` is missing.
- Qwen3 ForcedAligner needs `nagisa` for Japanese tokenization and `soynlp` for
  Korean tokenization. The first version supports ASR transcription, not forced
  alignment, so these are documented as future/advanced hints rather than part
  of `mac`.
- Ming Omni TTS (BailingMM) can need `onnx` when a downloaded model contains
  `campplus.onnx` without a prebuilt `campplus.safetensors`; its converter also
  imports `safetensors`. Keep this out of `mac`, but mark the BailingMM model
  note with `pip install onnx safetensors` if conversion fails.
- Voxtral TTS uses `mistral-common[audio]` for Tekken speech prompt encoding.
  That is already included by upstream `mlx-audio[tts]`, so no extra
  Voice Toolbox dependency is needed.
- Higgs Audio v3 imports `tokenizers` directly, but `transformers` already
  brings it in through the upstream core dependency set.
- OmniVoice README mentions `torchaudio` for voice cloning, but the current MLX
  runtime path uses `mlx_audio.audio_io` and an internal resampler, with no
  `torchaudio` import in the inspected runtime. Do not list `torchaudio` as a
  required dependency unless smoke testing proves a current runtime failure.
- `ffmpeg` is a host binary for non-WAV audio encode/decode paths
  (MP3/FLAC/OGG/Opus/WebM and M4A/AAC/WebM decode), not a Python extra. The
  first smoke path should use WAV so `ffmpeg` remains optional.

Implementation should add a small dependency-hint mapper around lazy model
loads/generation:

- Missing top-level `mlx_audio`: `install voice-toolbox[mac]`.
- Missing `misaki`: `pip install misaki` plus language-specific extras when
  the request uses Kokoro `j` or `z`.
- Missing `nagisa` or `soynlp`: mention Qwen3 ForcedAligner Japanese/Korean
  tokenization and the package to install.
- Missing `onnx` or `safetensors`: mention Ming Omni BailingMM campplus
  conversion and `pip install onnx safetensors`.
- Missing `mistral_common`: mention Voxtral TTS and `mlx-audio[tts]`.
- Normalize `ModuleNotFoundError`, direct `ImportError`, `ImportError.__cause__`,
  known `RuntimeError` messages, and generic conversion exceptions whose text
  mentions the known missing module.
- Any unknown import/load failure: include the selected provider model id, the
  resolved upstream model id, the missing module name when available, and the
  original error text.

Runtime dependency hints use an internal structured mapping keyed by provider
model id, upstream model id, and missing module. `ModelInfo.note` is display-only
metadata for the API/UI; provider error handling must not parse note strings.

## Provider Configuration

Add provider type `mlx_audio`.

Because `mlx_audio` is local and does not use an API endpoint or API key, update
configured provider metadata so local providers can omit network credentials:

- `ConfiguredProvider.type`: add `"mlx_audio"`.
- `ConfiguredProvider.base_url`: allow `str | None`.
- `ConfiguredProvider.api_key_env`: allow `str | None`.
- API readiness checks skip the key requirement when `api_key_env is None`.
- Provider summaries expose `requires_api_key: false` for local providers. The
  web key-status label should show a local/provider-ready state instead of
  "API key missing".

Default `mlx_audio` config uses provider-facing model ids. These ids are unique
per capability because `ModelInfo.capability` is a single value and configured
providers reject duplicate model ids. The provider maps these ids to upstream
Hugging Face repo ids before calling `mlx_audio`.

```toml
[[providers]]
id = "mlx-audio"
type = "mlx_audio"
name = "MLX Audio"
base_url = null
api_key_env = null
default_voice = "Ryan"

[providers.default_models]
tts_builtin = "qwen3-tts-0.6b-base"
tts_clone = "qwen3-tts-0.6b-base-clone"
asr = "mlx-community/Qwen3-ASR-0.6B-8bit"
```

Built-in model list should include:

- `qwen3-tts-0.6b-base`, capability `tts.builtin`, upstream
  `mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16`.
- `qwen3-tts-0.6b-base-clone`, capability `tts.clone`, upstream
  `mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16`, requires
  `clone_reference_text`.
- `qwen3-tts-1.7b-base-8bit`, upstream
  `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`.
- `longcat-audiodit-1b`, upstream
  `mlx-community/LongCat-AudioDiT-1B-bf16`.
- `ming-omni-tts-16.8b-a3b`, upstream
  `mlx-community/Ming-omni-tts-16.8B-A3B-bf16`, with a note that `onnx` and
  `safetensors` may be needed if campplus conversion runs.
- `higgs-audio-v3-tts-4b`, upstream `bosonai/higgs-audio-v3-tts-4b`.
- `mlx-community/Qwen3-ASR-0.6B-8bit` as default ASR.
- `mlx-community/Qwen3-ASR-1.7B-8bit`.

Default voices can start with Qwen3 examples (`Ryan`, `Aiden`, `Vivian`,
`Serena`) plus a generic `default` voice for models that ignore voice names.
Use `ModelInfo.note` for display-only dependency or memory warnings; avoid
adding new public API fields for this first pass. Runtime behavior uses
provider-owned alias and dependency-hint maps.

## Provider Architecture

Create `packages/voice_toolbox/src/voice_toolbox/providers/mlx_audio.py` with
`MlxAudioProvider`.

The provider follows the existing `VoiceProvider` protocol:

- `capabilities()` derives from configured models.
- `list_models()` and `list_voices()` return configured copies.
- `synthesize()` persists one artifact.
- `synthesize_bytes()` returns provider-ready audio bytes for chunking.
- `transcribe()` persists one transcript artifact.
- `transcribe_payload()` returns `TranscriptPayload` for chunking.

Model loading is lazy and cached per provider instance:

- TTS cache key: model id.
- ASR cache key: model id.
- Tests inject fake loader functions and fake models to avoid importing MLX.

The provider imports `mlx_audio` only inside loader paths. If the `mac` extra is
missing, operations fail with a clear `ProviderError`:

```text
mlx-audio dependency is not installed; install voice-toolbox[mac]
```

## TTS Data Flow

For `tts.builtin`:

1. Resolve model from `request.model` or `default_models.tts_builtin`.
2. Resolve the provider-facing model id to an upstream model id.
3. Load TTS model with `mlx_audio.tts.utils.load`.
   - For Ming Omni/BailingMM, pass `allow_patterns` matching upstream defaults
     plus `*.onnx` so `campplus.onnx` is available when conversion is needed.
     Add a fake-loader unit test that asserts this loader option.
4. Build generation kwargs:
   - `text=request.text`
   - `voice=request.voice_id` when present
   - `lang_code` from provider option `lang_code` or language inference default
   - `speed`, `temperature`, and other configured `provider_options`
5. Iterate `model.generate(...)`.
6. Concatenate returned `result.audio` chunks in order.
7. Write WAV bytes using `mlx_audio.audio_io.write`.

For `tts.clone`:

1. Require the existing clone consent and uploaded sample path.
2. Require `clone_reference_text` in the first version. Qwen3-TTS only takes
   the ICL voice-clone path when both `ref_audio` and `ref_text` are present;
   silently omitting the transcript would produce a weaker/non-clone path.
   Automatic ASR fill-in can be a later feature.
3. Pass `ref_audio=str(request.clone_sample_path)`.
4. Pass `ref_text=request.clone_reference_text`.
5. Use the same alias resolution, load, result merge, and WAV writing path.

`tts.design` remains unsupported even when a selected model could do voice design.
That avoids a method-dispatch matrix across Qwen3 variants in the first version.

## ASR Data Flow

For `asr.transcribe`:

1. Resolve model from `request.model` or `default_models.asr`.
2. Load STT model with `mlx_audio.stt.load`.
3. Map Voice Toolbox language values:
   - `auto` -> omit language when supported, otherwise `"auto"`.
   - `zh` -> `"Chinese"`.
   - `en` -> `"English"`.
4. Merge safe `provider_options` into `model.generate(...)`.
5. Extract `result.text`.
6. Convert `result.segments` when present into `TranscriptPayload.segments`.

The existing API language enum stays `auto | zh | en` in this first version.
Broader multilingual UI/API support is a later change.

Do not expose Qwen3 ForcedAligner as `asr.transcribe`. If a user configures a
ForcedAligner repo id under the `mlx_audio` ASR capability, reject it with
`UnsupportedCapability` explaining that forced alignment needs a future
`asr.align`-style capability with transcript input. Add a unit test for this
guard.

## Error Handling

Wrap provider failures in `ProviderError` with local, actionable messages:

- Missing dependency: install `voice-toolbox[mac]`.
- Missing model-specific dependency: include the selected model id and the
  package hint from the dependency mapper.
- Ming Omni/BailingMM missing conversion dependency or missing `campplus` file:
  include the selected model id, upstream model id, and the `onnx`/`safetensors`
  install hint.
- ForcedAligner configured as ASR: reject as unsupported because it requires
  transcript input and returns word alignment, not plain transcription.
- Unsupported platform: `mlx_audio provider requires Apple Silicon macOS`.
- Unknown model id: existing unsupported-model pattern.
- Empty generation: `mlx_audio generated no audio`.
- Missing transcript text: `mlx_audio response is missing transcript text`.

Provider metadata records:

- `model`
- `operation`
- `provider_id`
- `tts_mode`
- `source_text_length`
- `voice_id`
- clone upload hashes and sizes
- ASR upload hashes, sizes, mime type, and language

No raw text, local file path, or API-like secret is written to metadata.

## Config And Docs

Update:

- `pyproject.toml`: add `mac` extra.
- `defaults.py`: add MLX Audio models, voices, defaults, factory helper.
- `config.py`: fill defaults for `type = "mlx_audio"`.
- `voice_toolbox.toml.example`: add a commented MLX Audio provider block.
- `README.md`: document `rtk uv sync --extra mac` and local provider usage.
- `docs/smoke/mlx-audio.md`: add real smoke commands for TTS, clone, and ASR.
- `docs/smoke/mlx-audio.md`: include a compact model-specific dependency
  matrix for Kokoro, Ming Omni BailingMM, Qwen3 ForcedAligner, Voxtral TTS, and
  non-WAV `ffmpeg` paths.
- `docs/smoke/mlx-audio.md`: include a target-model smoke matrix:
  - Qwen3 TTS 0.6B builtin short WAV.
  - Qwen3 TTS 0.6B clone short WAV with required `ref_text`.
  - Qwen3 ASR 0.6B short WAV.
  - LongCat short WAV.
  - Higgs Audio v3 short WAV when hardware memory allows.
  - Ming Omni/BailingMM load-only plus a conversion-path note because the
    16.8B model is large.

Fallback config remains MiMo. MLX Audio is opt-in through TOML because it is
platform-specific and has large model downloads.

## Testing

Unit tests should not import or download real MLX models.

Add focused tests for:

- `mac` extra exists and is not part of `dev`.
- `mac` extra contains `mlx-audio[tts,stt]` but does not contain
  model-specific packages such as `misaki`, `nagisa`, `soynlp`, or `onnx`.
- `ConfiguredProvider` accepts `base_url = None` and `api_key_env = None` for
  `mlx_audio`.
- provider-facing alias ids map to upstream model ids and avoid duplicate
  configured model ids when one upstream repo supports multiple capabilities.
- provider factory builds `MlxAudioProvider`.
- provider summary marks `mlx_audio` as not requiring an API key.
- key readiness check does not block local provider operations.
- missing model-specific imports are converted to `ProviderError` messages with
  model id and install hint.
- Ming Omni BailingMM model metadata exposes the `onnx`/`safetensors` note.
- Ming Omni BailingMM loader passes `allow_patterns` that include `*.onnx`.
- Qwen3 clone rejects missing `clone_reference_text`.
- ForcedAligner model ids/configs are rejected for `asr.transcribe`.
- TTS builtin calls fake model with expected kwargs and writes WAV bytes.
- TTS clone passes `ref_audio` and `ref_text`.
- ASR maps language and returns transcript text.
- unsupported `tts.design` raises `UnsupportedCapability`.

Verification after implementation:

```bash
rtk uv run pytest tests/test_mlx_audio_provider.py tests/test_provider_config.py tests/test_api.py -q
rtk uv run ruff check packages/voice_toolbox/src apps/api/src tests
rtk uv run ty check
```

Real smoke tests require Apple Silicon macOS plus the `mac` extra and are manual.
