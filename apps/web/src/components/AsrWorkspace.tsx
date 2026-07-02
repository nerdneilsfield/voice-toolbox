import { type FormEvent, useMemo, useState } from "react";
import type { Artifact, ChunkingMode, Provider } from "../api";
import { useI18n } from "../i18n";
import { useAsrChunkUpload } from "../hooks/useAsrChunkUpload";
import { useProviderOptions } from "../hooks/useProviderOptions";
import { asrLanguageOptionsForProvider } from "../lib/asrLanguages";
import {
  optionsForCapability,
  sanitizeOptionValues,
  selectedModel,
  validateOptionValues,
} from "../lib/providerOptions";
import { AdvancedOptionsCard } from "./AdvancedOptionsCard";
import { ChunkingControls } from "./ChunkingControls";
import { Notice } from "./Primitives";
import { TranscriptPanel } from "./TranscriptPanel";

type AsrWorkspaceProps = {
  provider: Provider | null;
  providerId: string;
  model: string | null;
  onModelChange: (value: string) => void;
  asrSupported: boolean;
  /** Controlled transcript result so history clicks (handled by the parent)
   *  can populate the panel without the workspace owning the artifact. */
  artifact: Artifact | null;
  transcript: string;
  resultState: "idle" | "loading" | "error";
  onResult: (artifact: Artifact | null, transcript: string) => void;
};

const AUDIO_ACCEPT = ".wav,.mp3,.flac,.m4a,.ogg,.webm,.aac,audio/*";

export function AsrWorkspace({
  provider,
  providerId,
  model,
  onModelChange,
  asrSupported,
  artifact,
  transcript,
  resultState,
  onResult,
}: AsrWorkspaceProps) {
  const { t } = useI18n();
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("auto");
  const [uploadStrategy, setUploadStrategy] = useState<"auto" | "browser" | "backend">("auto");
  const [chunkingMode, setChunkingMode] = useState<ChunkingMode>("auto");
  const [chunkSeconds, setChunkSeconds] = useState(90);
  const [overlapMs, setOverlapMs] = useState(1200);
  const [timestamps, setTimestamps] = useState(false);
  const [speakers, setSpeakers] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const modelObj = selectedModel(provider, model);
  const specs = useMemo(() => optionsForCapability(provider, modelObj, "asr.transcribe"), [provider, modelObj]);
  const [optionValues, setOptionValues] = useProviderOptions(providerId, "asr.transcribe", specs);
  const languageOptions = asrLanguageOptionsForProvider(provider);
  const supportsTimestamps = Boolean(modelObj?.transcript_capabilities?.timestamps);
  const supportsSpeakers = Boolean(modelObj?.transcript_capabilities?.speakers);

  const upload = useAsrChunkUpload({
    providerId,
    model,
    language,
    chunkSeconds,
    overlapMs,
    chunkingMode,
    uploadStrategy,
    transcriptTimestamps: timestamps,
    transcriptSpeakers: speakers,
  });

  // Strategy hint: explain which upload path applies. Shown always (not just
  // after a file is picked) so the user understands the trade-off up front.
  const strategyHint = useMemo(() => {
    const isWav = file && (file.type === "audio/wav" || file.type === "audio/x-wav" || /\.wav$/i.test(file.name));
    if (uploadStrategy === "backend") return t("asr.uploadHint.backend");
    if (uploadStrategy === "browser") return isWav ? t("asr.uploadHint.browser") : t("asr.uploadHint.backend");
    return isWav ? t("asr.uploadHint.browser") : t("asr.uploadHint.auto");
  }, [file, uploadStrategy, t]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) {
      setError(t("errors.asrAudioRequired"));
      return;
    }
    setError("");
    setSubmitting(true);
    onResult(null, "");
    try {
      const sanitized = sanitizeOptionValues(optionValues, specs);
      const errors = validateOptionValues(sanitized, specs);
      if (errors.length > 0) throw new Error(errors.join("; "));
      const providerOptions = sanitized as Record<string, unknown>;
      const result = await upload.run(file, providerOptions);
      const resp = await fetch(result.artifact.download_url);
      if (!resp.ok) throw new Error(t("errors.transcriptDownloadFailed", { status: resp.status }));
      const text = await resp.text();
      onResult(result.artifact, text);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("errors.asrRequestFailed"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="canvas" onSubmit={submit}>
      <section className="card">
        <div className="card-header">
          <span className="card-label">{t("asr.audio")}</span>
        </div>
        <label className="field">
          <span className="field-title">{t("asr.audioFile")}</span>
          <input
            type="file"
            accept={AUDIO_ACCEPT}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            required
          />
          {file ? <span className="field-hint">{file.name}</span> : null}
        </label>
        <label className="field">
          <span className="field-title">{t("asr.language")}</span>
          <select value={language} onChange={(event) => setLanguage(event.target.value)}>
            {languageOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.labelKey)}
              </option>
            ))}
          </select>
        </label>
        <ChunkingControls
          mode={chunkingMode}
          setMode={setChunkingMode}
          primaryLabel={t("asr.chunkSeconds")}
          primaryValue={chunkSeconds}
          setPrimaryValue={setChunkSeconds}
          primaryMin={10}
          secondaryLabel={t("asr.chunkOverlapMs")}
          secondaryValue={overlapMs}
          setSecondaryValue={setOverlapMs}
        />
        <label className="field">
          <span className="field-title">{t("asr.uploadStrategy")}</span>
          <select
            value={uploadStrategy}
            onChange={(event) => setUploadStrategy(event.target.value as "auto" | "browser" | "backend")}
          >
            <option value="auto">{t("asr.uploadStrategy.auto")}</option>
            <option value="browser">{t("asr.uploadStrategy.browser")}</option>
            <option value="backend">{t("asr.uploadStrategy.backend")}</option>
          </select>
        </label>
        {strategyHint ? <span className="field-hint">{strategyHint}</span> : null}
        {supportsTimestamps || supportsSpeakers ? (
          <div className="two-col-fields">
            {supportsTimestamps ? (
              <label className="checkbox-line">
                <input type="checkbox" checked={timestamps} onChange={(event) => setTimestamps(event.target.checked)} />
                <span>{t("asr.timestamps")}</span>
              </label>
            ) : null}
            {supportsSpeakers ? (
              <label className="checkbox-line">
                <input type="checkbox" checked={speakers} onChange={(event) => setSpeakers(event.target.checked)} />
                <span>{t("asr.speakers")}</span>
              </label>
            ) : null}
          </div>
        ) : null}
      </section>

      <AdvancedOptionsCard
        models={provider?.models.filter((m) => m.capability === "asr.transcribe") ?? []}
        selectedModel={model}
        onModelChange={onModelChange}
        optionSpecs={specs}
        optionValues={optionValues}
        onOptionValuesChange={setOptionValues}
      />

      <div className="card action-card">
        <div className="card-header">
          <span className="meta-label">
            <span>{t("tts.model")}</span>
            <span>{modelObj?.name ?? model ?? t("tts.modelNone")}</span>
          </span>
          <span className="format-pill">{language.toUpperCase()}</span>
        </div>
        {error ? <Notice variant="error">{error}</Notice> : null}
        {upload.progress ? <Notice>{upload.progress.message}</Notice> : null}
        {!asrSupported ? <Notice variant="error">{t("asr.unsupported")}</Notice> : null}
        <div className="action-row">
          <button className="primary-action" type="submit" disabled={submitting || !provider || !asrSupported}>
            {submitting ? (
              <>
                <span className="spinner" aria-hidden="true" />
                {t("asr.transcribing")}
              </>
            ) : (
              t("asr.transcribe")
            )}
          </button>
          {submitting && upload.active ? (
            <button className="btn btn-ghost" type="button" onClick={() => upload.cancel()}>
              {t("asr.cancelChunks")}
            </button>
          ) : null}
        </div>
      </div>

      {artifact || resultState === "loading" ? (
        <TranscriptPanel artifact={artifact} transcript={transcript} state={resultState} />
      ) : null}
    </form>
  );
}
