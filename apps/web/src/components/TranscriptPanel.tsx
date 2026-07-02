import { useEffect, useState } from "react";
import type { Artifact } from "../api";
import { transcriptDownloadUrl } from "../api";
import { useI18n } from "../i18n";
import { EmptyState, LoadingState } from "./Primitives";

type TranscriptDownloadFormat = "txt" | "srt" | "vtt" | "json";

function metadataBoolean(metadata: Record<string, unknown> | null | undefined, key: string): boolean {
  return metadata?.[key] === true;
}

export function TranscriptPanel({
  artifact,
  transcript,
  state,
}: {
  artifact: Artifact | null;
  transcript: string;
  state: "idle" | "loading" | "error";
}) {
  const { t } = useI18n();
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const [downloadFormat, setDownloadFormat] = useState<TranscriptDownloadFormat>("txt");
  const [downloadTimestamps, setDownloadTimestamps] = useState(false);
  const [downloadSpeakers, setDownloadSpeakers] = useState(false);
  const hasTimestamps = metadataBoolean(artifact?.metadata, "transcript_has_timestamps");
  const hasSpeakers = metadataBoolean(artifact?.metadata, "transcript_has_speakers");

  // srt/vtt imply timestamps; if the artifact has none, force txt.
  const effectiveFormat =
    !hasTimestamps && (downloadFormat === "srt" || downloadFormat === "vtt") ? "txt" : downloadFormat;

  useEffect(() => {
    if (!hasTimestamps && (downloadFormat === "srt" || downloadFormat === "vtt")) {
      setDownloadFormat("txt");
    }
    if (!hasTimestamps) setDownloadTimestamps(false);
    if (!hasSpeakers) setDownloadSpeakers(false);
  }, [downloadFormat, hasSpeakers, hasTimestamps]);

  const transcriptUrl = artifact
    ? transcriptDownloadUrl(artifact.id, effectiveFormat, {
        timestamps: downloadTimestamps && hasTimestamps,
        speakers: downloadSpeakers && hasSpeakers,
      })
    : "";

  async function copyTranscript() {
    if (!transcript.trim()) return;
    try {
      await navigator.clipboard.writeText(transcript);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 1400);
    } catch {
      setCopyState("failed");
      window.setTimeout(() => setCopyState("idle"), 1400);
    }
  }

  // Timestamp/speaker toggles are meaningful for txt output. For srt/vtt they
  // are baked into the format, so show them disabled with a hint rather than
  // hiding them only inside the txt branch.
  const togglesApply = effectiveFormat === "txt";

  return (
    <aside className="result-panel">
      <div className="result-heading">
        <span className="card-label">{t("result.transcript")}</span>
        {artifact ? <span className="format-pill">{t("common.chars", { count: transcript.length })}</span> : null}
      </div>
      {state === "idle" ? <EmptyState title={t("result.readyForTranscript")} /> : null}
      {state === "loading" ? <LoadingState lines={4} /> : null}
      {artifact ? (
        <div className="artifact-block">
          <div className="transcript-toolbar">
            <button type="button" onClick={copyTranscript} disabled={!transcript.trim()}>
              {copyState === "copied"
                ? t("result.copied")
                : copyState === "failed"
                  ? t("result.copyFailed")
                  : t("result.copy")}
            </button>
            <label className="download-format">
              <span>{t("result.downloadAs")}</span>
              <select
                value={effectiveFormat}
                onChange={(event) => setDownloadFormat(event.target.value as TranscriptDownloadFormat)}
              >
                <option value="txt">{t("transcriptFormat.txt")}</option>
                {hasTimestamps ? <option value="srt">{t("transcriptFormat.srt")}</option> : null}
                {hasTimestamps ? <option value="vtt">{t("transcriptFormat.vtt")}</option> : null}
                <option value="json">{t("transcriptFormat.json")}</option>
              </select>
            </label>
            {hasTimestamps ? (
              <label className={`checkbox-line compact-line${togglesApply ? "" : " disabled"}`}>
                <input
                  type="checkbox"
                  checked={togglesApply && downloadTimestamps}
                  disabled={!togglesApply}
                  onChange={(event) => setDownloadTimestamps(event.target.checked)}
                />
                <span>{t("asr.timestamps")}</span>
              </label>
            ) : null}
            {hasSpeakers ? (
              <label className={`checkbox-line compact-line${togglesApply ? "" : " disabled"}`}>
                <input
                  type="checkbox"
                  checked={togglesApply && downloadSpeakers}
                  disabled={!togglesApply}
                  onChange={(event) => setDownloadSpeakers(event.target.checked)}
                />
                <span>{t("asr.speakers")}</span>
              </label>
            ) : null}
          </div>
          <pre className="transcript-viewer">{transcript || t("result.emptyTranscript")}</pre>
          <a className="download-link" href={transcriptUrl}>
            {t("result.downloadTranscript")}
          </a>
        </div>
      ) : null}
    </aside>
  );
}
