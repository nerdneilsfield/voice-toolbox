import { useEffect, useMemo, useRef, useState } from "react";
import type { Provider, ProviderModel, Voice } from "../api";
import { selectDefaultVoice, selectModelForCapability } from "../lib/providerSelection";

/**
 * Derives model + voice selections for a provider, resetting them when the
 * provider changes (instead of letting each capability recompute in its own
 * chained effect). Replaces the modelProviderId/voiceProviderId "remember the
 * previous value" anti-pattern.
 */
export type ModelSelection = {
  builtin: string | null;
  design: string | null;
  clone: string | null;
  asr: string | null;
};

export type ProviderSelection = {
  models: ModelSelection;
  voiceId: string;
  setModel: (capability: keyof ModelSelection, value: string | null) => void;
  setVoiceId: (value: string) => void;
};

const INITIAL_MODELS: ModelSelection = { builtin: null, design: null, clone: null, asr: null };

export function useProviderSelection(provider: Provider | null, voices: Voice[]): ProviderSelection {
  const [models, setModels] = useState<ModelSelection>(INITIAL_MODELS);
  const [voiceId, setVoiceId] = useState("");
  const lastProviderId = useRef<string>("");

  // Single source of truth for "provider changed": recompute every derived
  // selection in one pass instead of 5 chained effects racing each other.
  useEffect(() => {
    const providerId = provider?.id ?? "";
    const providerChanged = providerId !== lastProviderId.current;
    lastProviderId.current = providerId;

    setModels((current) => ({
      builtin: selectModelForCapability(provider, "tts.builtin", providerChanged ? null : current.builtin),
      design: selectModelForCapability(provider, "tts.design", providerChanged ? null : current.design),
      clone: selectModelForCapability(provider, "tts.clone", providerChanged ? null : current.clone),
      asr: selectModelForCapability(provider, "asr.transcribe", providerChanged ? null : current.asr),
    }));
    // Provider changed -> reset to default. But voices load asynchronously,
    // so the first run may see an empty voice list and leave voiceId blank.
    // Backfill the default once voices arrive and voiceId is still empty
    // (current value not in the list), otherwise the controlled select drifts
    // out of sync with React state.
    setVoiceId((current) => {
      if (providerChanged) return selectDefaultVoice(provider, voices, null) ?? "";
      const stillValid = current && voices.some((voice) => voice.id === current);
      if (!current && voices.length > 0) return selectDefaultVoice(provider, voices, null) ?? voices[0].id;
      return stillValid ? current : (selectDefaultVoice(provider, voices, null) ?? "");
    });
  }, [provider, voices]);

  const setModel = (capability: keyof ModelSelection, value: string | null) => {
    setModels((current) => ({ ...current, [capability]: value }));
  };

  return useMemo(() => ({ models, voiceId, setModel, setVoiceId }), [models, voiceId]);
}

export function modelsForCapability(provider: Provider | null, capability: string): ProviderModel[] {
  return provider?.models.filter((model) => model.capability === capability) ?? [];
}
