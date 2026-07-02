import { describe, expect, it } from "vitest";
import type { Provider } from "../api";
import { providerHasMissingApiKey, providerRequiresApiKey } from "./providerReadiness";

const baseProvider: Provider = {
  id: "mimo",
  name: "MiMo",
  capabilities: ["tts.builtin"],
  models: [],
};

describe("provider readiness", () => {
  it("treats local providers as not requiring API keys", () => {
    const provider: Provider = {
      ...baseProvider,
      id: "mlx-audio",
      type: "mlx_audio",
      requires_api_key: false,
      has_api_key: false,
    };

    expect(providerRequiresApiKey(provider)).toBe(false);
    expect(providerHasMissingApiKey(provider)).toBe(false);
  });

  it("keeps network provider missing-key behavior", () => {
    const provider: Provider = {
      ...baseProvider,
      requires_api_key: true,
      has_api_key: false,
    };

    expect(providerRequiresApiKey(provider)).toBe(true);
    expect(providerHasMissingApiKey(provider)).toBe(true);
  });

  it("defaults legacy summaries to key-required when has_api_key is present", () => {
    const provider: Provider = {
      ...baseProvider,
      has_api_key: false,
    };

    expect(providerRequiresApiKey(provider)).toBe(true);
    expect(providerHasMissingApiKey(provider)).toBe(true);
  });
});
