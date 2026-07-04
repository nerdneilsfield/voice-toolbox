import { describe, expect, it } from "vitest";
import { formatPodcastDuration, podcastProgressTiming } from "./podcastProgress";

describe("podcastProgressTiming", () => {
  it("estimates remaining time from completed segments", () => {
    const timing = podcastProgressTiming(
      {
        created_at: "2026-07-04T00:00:00.000Z",
        updated_at: "2026-07-04T00:02:00.000Z",
        current_segment: 3,
        total_segments: 5,
      },
      Date.parse("2026-07-04T00:02:00.000Z"),
    );

    expect(timing).toEqual({ elapsedSeconds: 120, remainingSeconds: 180 });
  });

  it("waits for a completed segment before estimating remaining time", () => {
    const timing = podcastProgressTiming(
      {
        created_at: "2026-07-04T00:00:00.000Z",
        current_segment: 1,
        total_segments: 5,
      },
      Date.parse("2026-07-04T00:00:30.000Z"),
    );

    expect(timing).toEqual({ elapsedSeconds: 30, remainingSeconds: null });
  });
});

describe("formatPodcastDuration", () => {
  it("formats durations for progress UI", () => {
    expect(formatPodcastDuration(0)).toBe("0:00");
    expect(formatPodcastDuration(65)).toBe("1:05");
    expect(formatPodcastDuration(3661)).toBe("1:01:01");
  });
});
