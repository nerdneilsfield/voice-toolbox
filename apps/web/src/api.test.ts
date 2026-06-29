import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createAsrChunkSession,
  finishAsrChunkSession,
  getArtifacts,
  synthesizeBuiltin,
  transcriptDownloadUrl,
} from "./api";

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

  it("posts TTS file and provider options as JSON object string", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonOperationResponse("audio"));
    const file = new File(["# Hello"], "script.md", { type: "text/markdown" });

    await synthesizeBuiltin({
      providerId: "fish",
      text: "",
      textFile: file,
      textFormat: "markdown",
      voiceId: "voice-1",
      model: "s1",
      chunkingMode: "force",
      chunkMaxChars: 1200,
      chunkSilenceMs: 80,
      providerOptions: { speed: 1.25, style: "bright" },
    });

    const body = fetchMock.mock.calls[0][1]?.body as FormData;
    expect(body.get("text_file")).toBe(file);
    expect(body.get("text")).toBeNull();
    expect(body.get("provider_options")).toBe(JSON.stringify({ speed: 1.25, style: "bright" }));
    expect(body.get("chunking_mode")).toBe("force");
  });

  it("creates ASR browser chunk session with source duration and provider options", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ session_id: "s1", browser_slice_formats: ["wav"] }), {
        headers: { "content-type": "application/json" },
      }),
    );

    await createAsrChunkSession({
      providerId: "mimo",
      model: "mimo-v2.5-asr",
      language: "zh",
      sourceDurationMs: 125000,
      totalChunks: 3,
      sourceFileName: "meeting.wav",
      transcriptTimestamps: true,
      transcriptSpeakers: true,
      providerOptions: { domain: "finance" },
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/v1/asr/chunk-sessions");
    const body = init?.body as FormData;
    expect(body.get("source_duration_ms")).toBe("125000");
    expect(body.get("provider_options")).toBe(JSON.stringify({ domain: "finance" }));
    expect(body.get("transcript_timestamps")).toBe("true");
    expect(body.get("transcript_speakers")).toBe("true");
  });

  it("finishes ASR browser chunk session with provider options", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonOperationResponse("transcript"));

    await finishAsrChunkSession({
      sessionId: "session-1",
      providerId: "mimo",
      model: "mimo-v2.5-asr",
      language: "auto",
      transcriptTimestamps: true,
      providerOptions: { domain: "medical" },
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/v1/asr/chunk-sessions/session-1/finish");
    const body = init?.body as FormData;
    expect(body.get("provider_options")).toBe(JSON.stringify({ domain: "medical" }));
    expect(body.get("transcript_timestamps")).toBe("true");
  });

  it("fetches artifacts with limit", async () => {
    const mockArtifact = {
      id: "test-1",
      provider_id: "mimo",
      operation: "tts",
      kind: "audio",
      mime_type: "audio/wav",
      created_at: "2026-06-28T12:00:00+00:00",
      download_url: "/v1/artifacts/test-1/download",
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ artifacts: [mockArtifact] }), {
        headers: { "content-type": "application/json" },
      }),
    );

    const artifacts = await getArtifacts(10);

    expect(globalThis.fetch).toHaveBeenCalledWith("/v1/artifacts?limit=10");
    expect(artifacts).toEqual([mockArtifact]);
  });

  it("throws on non-ok response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("Server error", { status: 500 }));

    await expect(getArtifacts()).rejects.toThrow("Server error");
  });

  it("builds transcript download URLs with format and txt render flags", () => {
    expect(transcriptDownloadUrl("a/b", "txt", { timestamps: true, speakers: true })).toBe(
      "/v1/artifacts/a%2Fb/transcript?format=txt&timestamps=true&speakers=true",
    );
    expect(transcriptDownloadUrl("artifact-1", "vtt")).toBe("/v1/artifacts/artifact-1/transcript?format=vtt");
  });
});

function jsonOperationResponse(kind: "audio" | "transcript") {
  return new Response(
    JSON.stringify({
      operation: {
        operation_id: "op-1",
        operation: kind === "audio" ? "tts" : "asr",
        status: "completed",
        started_at: "2026-01-01T00:00:00Z",
        finished_at: "2026-01-01T00:00:01Z",
        artifact_ids: ["op-1"],
      },
      artifact: {
        id: "op-1",
        kind,
        provider_id: "mimo",
        operation: kind === "audio" ? "tts" : "asr",
        mime_type: kind === "audio" ? "audio/wav" : "text/plain; charset=utf-8",
        created_at: "2026-01-01T00:00:01Z",
        metadata: {},
        download_url: "/v1/artifacts/op-1/download",
      },
    }),
    { status: 200, headers: { "content-type": "application/json" } },
  );
}
