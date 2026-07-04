import type { Artifact } from "../api";
import type { TranslationKey } from "../i18n/types";

export function formatHistoryTitle(
  artifact: Artifact,
  t: (key: TranslationKey, values?: Record<string, string | number>) => string,
): string {
  const op = artifact.operation ?? "unknown";
  const kind = artifact.kind ?? "unknown";
  if (op === "podcast") {
    const speakers = Number(artifact.metadata?.podcast_speaker_count ?? 0);
    const segments = Number(artifact.metadata?.podcast_segment_count ?? 0);
    return t("history.podcastTitle", { speakers, segments });
  }
  if (op === "tts" && kind === "audio") {
    const mode = String(artifact.metadata?.tts_mode ?? "unknown");
    if (mode === "builtin") return t("history.titleTtsBuiltin");
    if (mode === "design") return t("history.titleTtsDesign");
    if (mode === "clone") return t("history.titleTtsClone");
    return t("history.titleUnknown", { op, kind });
  }
  if (op === "asr" || kind === "transcript") return t("history.titleAsr");
  return t("history.titleUnknown", { op, kind });
}
