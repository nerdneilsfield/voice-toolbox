import { afterEach, describe, expect, it, vi } from "vitest";
import { synthesizeBuiltin } from "./api";

describe("api client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("posts built-in TTS to dedicated route without mode field", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          operation: {
            operation_id: "op-1",
            operation: "tts",
            status: "completed",
            started_at: "2026-01-01T00:00:00Z",
            finished_at: "2026-01-01T00:00:01Z",
            artifact_ids: ["op-1"],
          },
          artifact: {
            id: "op-1",
            kind: "audio",
            provider_id: "mimo",
            operation: "tts",
            mime_type: "audio/wav",
            created_at: "2026-01-01T00:00:01Z",
            metadata: {},
            download_url: "/v1/artifacts/op-1/download",
          },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    await synthesizeBuiltin({
      providerId: "mimo",
      text: "hello",
      textFormat: "plain",
      voiceId: "Mia",
      model: "mimo-v2.5-tts",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/v1/tts/builtin");
    expect(init?.method).toBe("POST");
    const body = init?.body;
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("mode")).toBeNull();
    expect((body as FormData).get("voice_id")).toBe("Mia");
  });
});
