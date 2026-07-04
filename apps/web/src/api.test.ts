import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cancelPodcastJob,
  createPodcastJob,
  createAsrChunkSession,
  deleteAsrChunkSession,
  finishAsrChunkSession,
  getArtifacts,
  getPodcastJob,
  synthesizeBuiltin,
  transcriptDownloadUrl,
  uploadAsrChunk,
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

  it("omits empty built-in TTS voice id for models without preset voices", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonOperationResponse("audio"));

    await synthesizeBuiltin({
      providerId: "mlx-audio",
      text: "hello",
      textFormat: "plain",
      voiceId: "",
      model: "longcat-audiodit-1b",
    });

    const body = fetchMock.mock.calls[0][1]?.body as FormData;
    expect(body.get("voice_id")).toBeNull();
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
    const uploaded = body.get("text_file") as File;
    expect(uploaded.name).toBe("script.md");
    expect(uploaded.type).toBe("text/markdown");
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
    expect(body.get("source_duration_ms")).toBeNull();
    expect(body.get("provider_options")).toBe(JSON.stringify({ domain: "medical" }));
    expect(body.get("transcript_timestamps")).toBe("true");
  });

  it("uploads ASR browser chunks in sequence payload shape", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ session_id: "session-1", received_chunks: 1, total_chunks: 2 }), {
        headers: { "content-type": "application/json" },
      }),
    );
    const chunk = new Blob(["riff"], { type: "audio/wav" });

    await uploadAsrChunk({
      sessionId: "session-1",
      file: chunk,
      fileName: "meeting.0.wav",
      chunkIndex: 0,
      offsetMs: 0,
      durationMs: 60000,
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/v1/asr/chunk-sessions/session-1/chunks");
    const body = init?.body as FormData;
    expect(body.get("chunk_index")).toBe("0");
    expect(body.get("offset_ms")).toBe("0");
    expect(body.get("duration_ms")).toBe("60000");
    const file = body.get("file") as File;
    expect(file.name).toBe("meeting.0.wav");
    expect(file.type).toBe("audio/wav");
  });

  it("deletes ASR browser chunk sessions for cancel cleanup", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ deleted: true }), {
        headers: { "content-type": "application/json" },
      }),
    );

    await deleteAsrChunkSession("session/1");

    expect(fetchMock).toHaveBeenCalledWith("/v1/asr/chunk-sessions/session%2F1", { method: "DELETE" });
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

  it("creates podcast jobs with speaker voices JSON", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ job_id: "podcast-1", status: "queued" }), {
        headers: { "content-type": "application/json" },
      }),
    );

    await createPodcastJob({
      providerId: "mimo",
      model: "fake-tts",
      script: "Alice: hello",
      scriptFormat: "speaker_colon",
      defaultPauseMs: 350,
      speakerVoices: { alice: "Mia" },
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/v1/podcast/jobs");
    const body = init?.body as FormData;
    expect(body.get("provider_id")).toBe("mimo");
    expect(body.get("model")).toBe("fake-tts");
    expect(body.get("script")).toBe("Alice: hello");
    expect(body.get("script_format")).toBe("speaker_colon");
    expect(body.get("default_pause_ms")).toBe("350");
    expect(body.get("speaker_voices")).toBe(JSON.stringify({ alice: "Mia" }));
  });

  it("fetches podcast job status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ job_id: "podcast-1", status: "completed" }), {
        headers: { "content-type": "application/json" },
      }),
    );

    await getPodcastJob("podcast/1");

    expect(globalThis.fetch).toHaveBeenCalledWith("/v1/podcast/jobs/podcast%2F1");
  });

  it("cancels podcast jobs", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ job_id: "podcast-1", status: "cancelled" }), {
        headers: { "content-type": "application/json" },
      }),
    );

    await cancelPodcastJob("podcast/1");

    expect(globalThis.fetch).toHaveBeenCalledWith("/v1/podcast/jobs/podcast%2F1", { method: "DELETE" });
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
