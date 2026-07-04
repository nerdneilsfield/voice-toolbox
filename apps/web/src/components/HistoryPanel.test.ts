import { describe, expect, it } from "vitest";
import type { Artifact } from "../api";
import type { TranslationKey } from "../i18n/types";
import { formatHistoryTitle } from "./historyTitle";

const t = (key: TranslationKey, values?: Record<string, string | number>) => {
  if (key === "history.podcastTitle") {
    return `podcast · ${values?.speakers} speakers · ${values?.segments} segments`;
  }
  return key;
};

describe("formatHistoryTitle", () => {
  it("formats podcast artifacts with speaker and segment counts", () => {
    const artifact: Artifact = {
      id: "p1",
      kind: "audio",
      provider_id: "mimo",
      operation: "podcast",
      mime_type: "audio/wav",
      created_at: "2026-01-01T00:00:00Z",
      metadata: { podcast_speaker_count: 2, podcast_segment_count: 8 },
      download_url: "/v1/artifacts/p1/download",
    };

    expect(formatHistoryTitle(artifact, t)).toBe("podcast · 2 speakers · 8 segments");
  });
});
