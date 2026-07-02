import { describe, expect, it } from "vitest";
import type { Provider, Voice } from "../api";
import { selectDefaultVoice, selectModelForCapability, voicesForModel } from "./providerSelection";

const provider: Provider = {
  id: "mimo",
  name: "MiMo",
  capabilities: ["tts.builtin", "asr.transcribe"],
  default_voice: "Mia",
  default_models: { tts_builtin: "tts-default", asr: "asr-default" },
  models: [
    { id: "tts-first", name: "First", capability: "tts.builtin" },
    { id: "tts-default", name: "Default", capability: "tts.builtin" },
    { id: "asr-default", name: "ASR", capability: "asr.transcribe" },
  ],
};

const voices: Voice[] = [
  { id: "冰糖", name: "冰糖" },
  { id: "Mia", name: "Mia" },
];

describe("provider selection", () => {
  it("keeps current valid model", () => {
    expect(selectModelForCapability(provider, "tts.builtin", "tts-first")).toBe("tts-first");
  });

  it("uses configured default model before first model", () => {
    expect(selectModelForCapability(provider, "tts.builtin", "missing")).toBe("tts-default");
  });

  it("uses configured default model when provider changes and current is omitted", () => {
    expect(selectModelForCapability(provider, "tts.builtin", null)).toBe("tts-default");
  });

  it("returns null without provider or matching models", () => {
    expect(selectModelForCapability(null, "tts.builtin", "tts-first")).toBeNull();
    expect(selectModelForCapability(provider, "tts.clone", null)).toBeNull();
  });

  it("uses configured default voice", () => {
    expect(selectDefaultVoice(provider, voices, null)).toBe("Mia");
  });

  it("keeps current valid voice on same provider refresh", () => {
    expect(selectDefaultVoice(provider, voices, "冰糖")).toBe("冰糖");
  });

  it("uses selected model voices before provider voices", () => {
    const mlxProvider: Provider = {
      id: "mlx-audio",
      name: "MLX Audio",
      capabilities: ["tts.builtin"],
      default_models: { tts_builtin: "qwen3" },
      models: [
        {
          id: "qwen3",
          name: "Qwen3",
          capability: "tts.builtin",
          voices: [
            { id: "Ryan", name: "Ryan" },
            { id: "Aiden", name: "Aiden" },
          ],
        },
        { id: "longcat", name: "LongCat", capability: "tts.builtin", voices: [] },
      ],
      voices: [{ id: "legacy", name: "Legacy" }],
    };

    expect(voicesForModel(mlxProvider, mlxProvider.voices ?? [], "qwen3").map((voice) => voice.id)).toEqual([
      "Ryan",
      "Aiden",
    ]);
  });

  it("removes model voices when selected model has none", () => {
    const mlxProvider: Provider = {
      id: "mlx-audio",
      name: "MLX Audio",
      capabilities: ["tts.builtin"],
      models: [
        { id: "qwen3", name: "Qwen3", capability: "tts.builtin", voices: [{ id: "Ryan", name: "Ryan" }] },
        { id: "longcat", name: "LongCat", capability: "tts.builtin", voices: [] },
      ],
      voices: [],
    };

    expect(voicesForModel(mlxProvider, [], "longcat")).toEqual([]);
  });
});
