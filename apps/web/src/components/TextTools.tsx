import type { TextFormat, ChunkingMode } from "../api";
import { useI18n } from "../i18n";
import { ChunkingControls } from "./ChunkingControls";

type TextToolsProps = {
  textFormat: TextFormat;
  setTextFormat: (value: TextFormat) => void;
  previewState: "idle" | "loading" | "success" | "error";
  previewError: string;
  cleanedPreview: string;
  onPreview: () => void;
  // Chunking (TTS-specific: max chars / silence)
  chunkingMode: ChunkingMode;
  setChunkingMode: (value: ChunkingMode) => void;
  chunkMaxChars: number;
  setChunkMaxChars: (value: number) => void;
  chunkSilenceMs: number;
  setChunkSilenceMs: (value: number) => void;
};

export function TextTools({
  textFormat,
  setTextFormat,
  previewState,
  previewError,
  cleanedPreview,
  onPreview,
  chunkingMode,
  setChunkingMode,
  chunkMaxChars,
  setChunkMaxChars,
  chunkSilenceMs,
  setChunkSilenceMs,
}: TextToolsProps) {
  const { t } = useI18n();
  return (
    <section className="card">
      <div className="card-header">
        <span className="card-label">{t("tts.textFormat")}</span>
        <div className="card-actions">
          <select
            className="select-input"
            value={textFormat}
            onChange={(event) => setTextFormat(event.target.value as TextFormat)}
          >
            <option value="plain">{t("tts.textFormatOption.plain")}</option>
            <option value="markdown">{t("tts.textFormatOption.markdown")}</option>
            <option value="auto">{t("tts.textFormatOption.auto")}</option>
          </select>
          <button className="btn btn-primary" type="button" onClick={onPreview} disabled={previewState === "loading"}>
            {previewState === "loading" ? t("tts.previewing") : t("tts.preview")}
          </button>
        </div>
      </div>
      <ChunkingControls
        mode={chunkingMode}
        setMode={setChunkingMode}
        primaryLabel={t("tts.chunkMaxChars")}
        primaryValue={chunkMaxChars}
        setPrimaryValue={setChunkMaxChars}
        secondaryLabel={t("tts.chunkSilenceMs")}
        secondaryValue={chunkSilenceMs}
        setSecondaryValue={setChunkSilenceMs}
      />
      {previewError ? <div className="notice error compact">{previewError}</div> : null}
      {cleanedPreview ? <pre className="cleaned-preview">{cleanedPreview}</pre> : null}
    </section>
  );
}
