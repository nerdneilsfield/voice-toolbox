# MLX Audio Model Voices Design

## Goal

Make MLX Audio voice selection model-scoped instead of provider-scoped. Different
MLX TTS models expose different voice behavior: Qwen3 base models have named
speakers, while LongCat, Ming Omni, and Higgs Audio v3 primarily use zero-shot
or reference-audio voice control.

## Problem

The first MLX Audio provider design reused the provider-wide `voices` list used
by MiMo and Fish Audio. That makes the web UI offer the same voice picker for
all MLX TTS models. This is wrong for MLX Audio because `Ryan`, `Aiden`,
`Vivian`, and `Serena` are Qwen3 examples, not universal MLX Audio voices.

Provider-wide voices cause two bad outcomes:

- Users can select a Qwen3 speaker for LongCat, Ming Omni, or Higgs even when
  that model ignores it or expects reference audio.
- The UI cannot explain why some models need `clone_reference_text`,
  `ref_audio`, `ref_text`, or model-specific generation options instead of a
  simple preset voice.

## Upstream Model Behavior

Known model voice behavior from `Blaizzy/mlx-audio` docs:

- Qwen3-TTS base generation accepts named speakers. Built-in speakers include
  Chinese voices `Vivian`, `Serena`, `Uncle_Fu`, `Dylan`, `Eric`, and English
  voices `Ryan`, `Aiden`.
- Qwen3-TTS clone path uses the same upstream base model, but voice identity
  comes from `ref_audio` plus `ref_text`; preset voice selection should not be
  required for clone mode.
- LongCat AudioDiT supports zero-shot generation and reference-audio voice
  cloning. It does not share the Qwen3 preset speaker list.
- Ming Omni TTS uses reference audio, reference text, prompts, and style
  instructions. It also has model-specific artifact/dependency behavior.
- Higgs Audio v3 uses reference clips and transcripts for voice cloning and
  inline control tokens for style/prosody. It does not expose Qwen3 speakers.

## Architecture

Keep existing provider-wide voices for providers where voices are naturally
provider-wide. Add model-scoped voices for models that need them.

`ModelInfo` gains an optional `voices: list[VoiceInfo]` field. Existing API
model summaries already serialize model objects, so the web client can read
`model.voices` without adding a new endpoint. Existing providers can leave the
field empty.

MLX Audio defaults move Qwen3 speakers from provider-level `MLX_AUDIO_VOICES`
onto Qwen3 builtin `ModelInfo` entries. Provider-level MLX voices become empty
or only contain values that truly apply across all MLX TTS models. There is no
known universal MLX voice, so the default should be empty.

The web UI resolves voices for TTS from the selected model first:

1. If the selected model has model-scoped voices, show those voices.
2. Otherwise fall back to provider voices for legacy providers.
3. If no voices apply and the active TTS mode is builtin, hide the voice picker
   or show a neutral disabled state depending on the existing component pattern.
4. Clone mode does not require a preset voice for MLX Audio; it relies on
   uploaded reference audio and clone reference text.

The backend validates MLX voice usage against the selected TTS model:

- If the selected model defines voices, `voice_id` must be one of them.
- If the selected model defines no voices and the model is known not to use
  preset voices, the provider must not pass an arbitrary `voice` kwarg.
- Qwen3 builtin still passes the selected voice to upstream `model.generate`.
- Clone requests pass `ref_audio` and `ref_text` and should not require or pass
  preset `voice` unless a future model explicitly declares clone voices.

## Configuration

TOML remains backwards-compatible. Provider-level `voices` continues to parse
and still applies to existing providers. Model-scoped voices can be configured
under a model block:

```toml
[[providers.models]]
id = "qwen3-tts-0.6b-base"
name = "Qwen3 TTS 0.6B Base"
capability = "tts.builtin"

[[providers.models.voices]]
id = "Ryan"
name = "Ryan"
language = "en"
gender = "male"
```

Default MLX config should not require users to write these blocks manually; it
fills Qwen3 model voices from built-in defaults.

## Docs

README should document:

- `voice-toolbox[mac]` installs MLX Audio only when requested.
- MLX voices are model-specific.
- Qwen3 builtin voices: `Ryan`, `Aiden`, `Vivian`, `Serena`, `Uncle_Fu`,
  `Dylan`, `Eric`.
- LongCat, Ming Omni, and Higgs should be described as reference/zero-shot
  models rather than Qwen3 speaker-preset models.
- Ming Omni may need `onnx` and `safetensors` conversion artifacts.

Add or update a smoke doc for MLX Audio with one Qwen3 builtin TTS command and
one Qwen3 ASR command. Reference-heavy models can be documented as advanced
manual checks instead of part of the first smoke path.

## Testing

Backend tests should cover:

- MLX Qwen3 model summaries expose model-scoped voices.
- MLX provider summary does not expose Qwen3 voices as provider-wide universal
  voices.
- Qwen3 builtin TTS accepts a Qwen3 voice and passes it upstream.
- LongCat/Ming/Higgs builtin TTS does not pass a Qwen3 `voice` kwarg.
- Invalid Qwen3 voice raises a clear provider error.
- Existing MiMo/Fish/OpenRouter provider-wide voice behavior remains unchanged.

Web tests should cover:

- Voice picker uses selected model voices when present.
- Switching from Qwen3 to LongCat removes Qwen3 voices from the picker.
- Switching back to Qwen3 restores Qwen3 voices.

## Non-Goals

This design does not add full `tts.design`, multi-reference voice cloning UI,
alignment, STS, VAD, diarization, or a complete model-specific options system.
Those can build on model-scoped metadata later.
