import { describe, expect, it } from "vitest";
import type { Provider, Voice } from "../api";
import { selectDefaultVoice, selectModelForCapability } from "./providerSelection";

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

  it("uses configured default voice", () => {
    expect(selectDefaultVoice(provider, voices, null)).toBe("Mia");
  });
});
