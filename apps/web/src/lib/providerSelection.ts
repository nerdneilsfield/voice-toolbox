import type { Capability, Provider, Voice } from "../api";

export function selectModelForCapability(
  provider: Provider | null | undefined,
  capability: Capability,
  currentModelId?: string | null,
): string | null {
  const models = provider?.models.filter((model) => model.capability === capability) ?? [];
  if (currentModelId && models.some((model) => model.id === currentModelId)) {
    return currentModelId;
  }
  const defaultKeyByCapability: Record<string, keyof NonNullable<Provider["default_models"]>> = {
    "tts.builtin": "tts_builtin",
    "tts.design": "tts_design",
    "tts.clone": "tts_clone",
    "asr.transcribe": "asr",
  };
  const defaultKey = defaultKeyByCapability[capability];
  const configuredDefault = defaultKey ? provider?.default_models?.[defaultKey] : null;
  if (configuredDefault && models.some((model) => model.id === configuredDefault)) {
    return configuredDefault;
  }
  return models[0]?.id ?? null;
}

export function selectDefaultVoice(
  provider: Provider | null | undefined,
  voices: Voice[],
  currentVoiceId?: string | null,
): string | null {
  if (currentVoiceId && voices.some((voice) => voice.id === currentVoiceId)) {
    return currentVoiceId;
  }
  const configuredDefault = provider?.default_voice;
  if (configuredDefault && voices.some((voice) => voice.id === configuredDefault)) {
    return configuredDefault;
  }
  return voices[0]?.id ?? null;
}

export function voicesForModel(
  provider: Provider | null | undefined,
  providerVoices: Voice[],
  modelId?: string | null,
): Voice[] {
  const model = provider?.models.find((item) => item.id === modelId);
  if (model?.voices !== undefined && model.voices.length > 0) {
    return model.voices;
  }
  if (provider?.type === "mlx_audio") {
    return [];
  }
  return providerVoices;
}
