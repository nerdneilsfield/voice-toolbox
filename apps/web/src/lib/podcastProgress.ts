import type { PodcastJobStatus } from "../api";

export type PodcastProgressTiming = {
  elapsedSeconds: number;
  remainingSeconds: number | null;
};

export function podcastProgressTiming(
  job: Pick<
    PodcastJobStatus,
    "created_at" | "updated_at" | "current_segment" | "total_segments" | "recent_segment_durations_ms"
  >,
  nowMs = Date.now(),
): PodcastProgressTiming {
  const startedMs = parseJobTime(job.created_at) ?? parseJobTime(job.updated_at) ?? nowMs;
  const elapsedSeconds = Math.max(0, Math.floor((nowMs - startedMs) / 1000));
  const totalSegments = safeSegmentCount(job.total_segments);
  const currentSegment = safeSegmentCount(job.current_segment);
  const completedSegments = Math.min(Math.max(currentSegment - 1, 0), totalSegments);
  const recentDurationsMs = validDurations(job.recent_segment_durations_ms);

  if (elapsedSeconds <= 0 || totalSegments <= 0 || completedSegments <= 0) {
    return { elapsedSeconds, remainingSeconds: null };
  }

  const remainingSegments = Math.max(totalSegments - completedSegments, 0);
  if (recentDurationsMs.length > 0) {
    const averageMs = recentDurationsMs.reduce((total, durationMs) => total + durationMs, 0) / recentDurationsMs.length;
    return {
      elapsedSeconds,
      remainingSeconds: Math.ceil((averageMs * remainingSegments) / 1000),
    };
  }

  return {
    elapsedSeconds,
    remainingSeconds: Math.ceil((elapsedSeconds / completedSegments) * remainingSegments),
  };
}

export function formatPodcastDuration(seconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainingSeconds = totalSeconds % 60;
  const paddedSeconds = String(remainingSeconds).padStart(2, "0");

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${paddedSeconds}`;
  }
  return `${minutes}:${paddedSeconds}`;
}

function parseJobTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function safeSegmentCount(value: number | null | undefined): number {
  if (value === null || value === undefined || !Number.isFinite(value)) return 0;
  return Math.max(0, Math.floor(value));
}

function validDurations(values: number[] | null | undefined): number[] {
  if (!Array.isArray(values)) return [];
  return values.filter((value) => Number.isFinite(value) && value >= 0).slice(-5);
}
