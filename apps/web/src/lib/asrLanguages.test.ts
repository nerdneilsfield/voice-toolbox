import { describe, expect, it } from "vitest";
import type { Provider } from "../api";
import { asrLanguageOptionsForProvider } from "./asrLanguages";

function provider(type: Provider["type"]): Provider {
  return {
    id: type ?? "unknown",
    name: type ?? "unknown",
    type,
    capabilities: ["asr.transcribe"],
    models: [],
    voices: [],
    options: [],
  };
}

describe("ASR language options", () => {
  it("keeps Mimo on its basic language set", () => {
    expect(asrLanguageOptionsForProvider(provider("mimo")).map((option) => option.value)).toEqual(["auto", "zh", "en"]);
  });

  it("exposes Fish Audio multilingual ASR choices", () => {
    expect(asrLanguageOptionsForProvider(provider("fish_audio")).map((option) => option.value)).toEqual([
      "auto",
      "zh",
      "yue",
      "en",
      "de",
      "es",
      "fr",
      "it",
      "pt",
      "ru",
      "ko",
      "ja",
    ]);
  });

  it("exposes Qwen3 languages for MLX Audio", () => {
    expect(asrLanguageOptionsForProvider(provider("mlx_audio")).map((option) => option.value)).toContain("ja");
  });
});
