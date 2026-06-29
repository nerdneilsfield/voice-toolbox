import { describe, expect, it } from "vitest";
import type { Provider } from "../api";
import {
  controlKindForOption,
  defaultOptionValues,
  optionsForCapability,
  sanitizeOptionValues,
  validateOptionValues,
} from "./providerOptions";

const provider: Provider = {
  id: "test",
  name: "Test",
  capabilities: ["tts.builtin"],
  options: [
    {
      key: "speed",
      label: "Speed",
      type: "number",
      capability: "tts.builtin",
      default: 1,
      min_value: 0.5,
      max_value: 2,
      advanced: false,
    },
    {
      key: "voice_style",
      label: "Style",
      type: "select",
      capability: "tts.builtin",
      choices: [
        { value: "calm", label: "Calm" },
        { value: "bright", label: "Bright" },
      ],
      default: "calm",
    },
    {
      key: "tags",
      label: "Tags",
      type: "multiselect",
      capability: "tts.builtin",
      choices: [
        { value: "news", label: "News" },
        { value: "story", label: "Story" },
      ],
    },
    {
      key: "notes",
      label: "Notes",
      type: "text",
      capability: "tts.builtin",
    },
  ],
  models: [
    {
      id: "base",
      name: "Base",
      capability: "tts.builtin",
      options: [
        {
          key: "speed",
          capability: "tts.builtin",
          default: 1.25,
          max_value: 1.5,
        },
      ],
    },
  ],
};

describe("provider option helpers", () => {
  it("renders fallback controls for every schema type", () => {
    expect(controlKindForOption({ key: "a", label: "A", type: "string", capability: "tts.builtin" })).toBe("input");
    expect(controlKindForOption({ key: "a", label: "A", type: "text", capability: "tts.builtin" })).toBe("textarea");
    expect(controlKindForOption({ key: "a", label: "A", type: "boolean", capability: "tts.builtin" })).toBe("checkbox");
    expect(controlKindForOption({ key: "a", label: "A", type: "integer", capability: "tts.builtin" })).toBe("number");
    expect(controlKindForOption({ key: "a", label: "A", type: "number", capability: "tts.builtin" })).toBe("number");
    expect(controlKindForOption({ key: "a", label: "A", type: "select", capability: "tts.builtin" })).toBe("select");
    expect(controlKindForOption({ key: "a", label: "A", type: "multiselect", capability: "tts.builtin" })).toBe(
      "multiselect",
    );
  });

  it("applies model-specific defaults and range overrides", () => {
    const specs = optionsForCapability(provider, provider.models[0], "tts.builtin");
    expect(defaultOptionValues(specs)).toMatchObject({ speed: 1.25, voice_style: "calm" });
    expect(specs.find((spec) => spec.key === "speed")?.max_value).toBe(1.5);
  });

  it("validates select and multiselect choices before submit", () => {
    const specs = optionsForCapability(provider, provider.models[0], "tts.builtin");
    const valid = sanitizeOptionValues({ voice_style: "bright", tags: ["news"], speed: 1.1 }, specs);
    expect(validateOptionValues(valid, specs)).toEqual([]);
    expect(validateOptionValues({ voice_style: "loud" }, specs)).toEqual([
      "voice_style must be one of the configured choices",
    ]);
    expect(validateOptionValues({ tags: ["bad"] }, specs)).toEqual(["tags must be one of the configured choices"]);
  });

  it("rejects non-finite numeric values before JSON submit", () => {
    const specs = optionsForCapability(provider, provider.models[0], "tts.builtin");

    expect(validateOptionValues({ speed: Number.NaN }, specs)).toEqual(["speed must be a finite number"]);
    expect(validateOptionValues({ speed: Number.POSITIVE_INFINITY }, specs)).toEqual(["speed must be a finite number"]);
  });

  it("drops stale invalid values during provider/model migration", () => {
    const specs = optionsForCapability(provider, provider.models[0], "tts.builtin");

    expect(sanitizeOptionValues({ speed: 2.5, voice_style: "loud", tags: ["bad"] }, specs)).toEqual({
      speed: 1.25,
      voice_style: "calm",
    });
  });

  it("does not truncate decimal numbers for integer options", () => {
    const specs = [
      {
        key: "seed",
        label: "Seed",
        type: "integer" as const,
        capability: "tts.builtin",
      },
    ];

    expect(sanitizeOptionValues({ seed: 1.5 }, specs)).toEqual({});
    expect(validateOptionValues({ seed: 1.5 }, specs)).toEqual(["seed must be an integer"]);
  });
});
