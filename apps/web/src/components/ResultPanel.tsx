import { useState } from "react";
import type { Artifact } from "../api";
import { useI18n } from "../i18n";
import { EmptyState, LoadingState } from "./Primitives";

type DownloadFormat = "source" | "wav" | "mp3" | "pcm" | "m4a" | "aac" | "flac" | "ogg" | "webm";

const FORMATS: DownloadFormat[] = ["source", "wav", "mp3", "pcm", "m4a", "aac", "flac", "ogg", "webm"];

function audioLabel(mimeType: string): string {
  const map: Record<string, string> = {
    "audio/mpeg": "MP3",
    "audio/mp3": "MP3",
    "audio/wav": "WAV",
    "audio/pcm": "PCM",
    "audio/l16": "PCM",
    "audio/mp4": "M4A",
    "audio/m4a": "M4A",
    "audio/aac": "AAC",
    "audio/flac": "FLAC",
    "audio/ogg": "OGG",
    "audio/webm": "WEBM",
  };
  return map[mimeType] ?? "audio";
}

function downloadUrlForFormat(url: string, format: DownloadFormat): string {
  return format === "source" ? url : `${url}?format=${encodeURIComponent(format)}`;
}

function shortId(id: string): string {
  return id.length <= 18 ? id : `${id.slice(0, 10)}...${id.slice(-6)}`;
}

export function ResultPanel({ artifact, state }: { artifact: Artifact | null; state: "idle" | "loading" | "error" }) {
  const { t } = useI18n();
  const [downloadFormat, setDownloadFormat] = useState<DownloadFormat>("source");
  const downloadUrl = artifact ? downloadUrlForFormat(artifact.download_url, downloadFormat) : "";
  const downloadLabel =
    downloadFormat === "source" || !artifact ? audioLabel(artifact?.mime_type ?? "") : downloadFormat.toUpperCase();

  return (
    <aside className="result-panel">
      <div className="result-heading">
        <span className="card-label">{t("result.output")}</span>
        {artifact ? <span className="format-pill">{audioLabel(artifact.mime_type)}</span> : null}
      </div>
      {state === "idle" ? <EmptyState title={t("result.readyForAudio")} /> : null}
      {state === "loading" ? <LoadingState lines={3} /> : null}
      {artifact ? (
        <div className="artifact-block">
          <audio className="audio-player" controls src={artifact.download_url} />
          <div className="result-actions">
            <label className="download-format">
              <span>{t("result.downloadAs")}</span>
              <select
                value={downloadFormat}
                onChange={(event) => setDownloadFormat(event.target.value as DownloadFormat)}
              >
                {FORMATS.map((format) => (
                  <option key={format} value={format}>
                    {format === "source" ? t("formats.source") : t(`formats.${format}` as const)}
                  </option>
                ))}
              </select>
            </label>
            <a className="download-link" href={downloadUrl}>
              {t("result.download", { label: downloadLabel })}
            </a>
          </div>
          <p className="artifact-meta">
            {shortId(artifact.id)} <span>•</span> {artifact.mime_type}
          </p>
        </div>
      ) : null}
    </aside>
  );
}
