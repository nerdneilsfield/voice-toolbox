import { type FormEvent, useEffect, useMemo, useState } from "react";
import type { Artifact, PodcastJobStatus, PodcastScriptFormat, Provider, TextFormat } from "../api";
import { createPodcastJob, getPodcastJob } from "../api";
import { useI18n } from "../i18n";
import { parsePodcastScriptPreview } from "../lib/podcastScript";
import { Notice } from "./Primitives";
import { ScriptField } from "./ScriptField";

type PodcastWorkspaceProps = {
  provider: Provider | null;
  providerId: string;
  model: string | null;
  onModelChange: (value: string) => void;
  voices: { id: string; name: string; note?: string | null }[];
  onResult: (artifact: Artifact | null) => void;
  onStateChange?: (state: "idle" | "loading" | "error") => void;
};

export function PodcastWorkspace({
  provider,
  providerId,
  model,
  onModelChange,
  voices,
  onResult,
  onStateChange,
}: PodcastWorkspaceProps) {
  const { t } = useI18n();
  const [script, setScript] = useState("Alice: Welcome to the show.\nBob: Glad to be here.");
  const [scriptFormat, setScriptFormat] = useState<PodcastScriptFormat>("speaker_colon");
  const [defaultPauseMs, setDefaultPauseMs] = useState(350);
  const [speakerVoices, setSpeakerVoices] = useState<Record<string, string>>({});
  const [job, setJob] = useState<PodcastJobStatus | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState("");

  const parsed = useMemo(
    () => parsePodcastScriptPreview(script, scriptFormat, defaultPauseMs),
    [defaultPauseMs, script, scriptFormat],
  );
  const models = provider?.models.filter((item) => item.capability === "tts.builtin") ?? [];
  const selectedModel = model || models[0]?.id || "";
  const missingVoice = parsed.speakers.some((speaker) => !speakerVoices[speaker.id]);
  const canSubmit =
    Boolean(provider && selectedModel && parsed.segments.length > 0) && parsed.errors.length === 0 && !missingVoice;

  useEffect(() => {
    onStateChange?.(state);
  }, [onStateChange, state]);

  useEffect(() => {
    setSpeakerVoices((current) => {
      const next: Record<string, string> = {};
      for (const speaker of parsed.speakers) {
        next[speaker.id] = current[speaker.id] ?? voices[0]?.id ?? "";
      }
      return next;
    });
  }, [parsed.speakers, voices]);

  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "running")) return;
    const timer = window.setInterval(() => {
      void getPodcastJob(job.job_id)
        .then((next) => {
          setJob(next);
          if (next.status === "completed" && next.artifact) {
            onResult(next.artifact);
            setState("idle");
          } else if (next.status === "failed") {
            setError(next.error_summary ?? "Podcast generation failed");
            setState("error");
          } else if (next.status === "cancelled") {
            setState("idle");
          }
        })
        .catch((err) => {
          setError(err instanceof Error ? err.message : "Podcast generation failed");
          setState("error");
        });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [job, onResult]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setState("loading");
    onResult(null);
    try {
      const created = await createPodcastJob({
        providerId,
        model: selectedModel,
        script,
        scriptFormat,
        defaultPauseMs,
        speakerVoices,
      });
      setJob(created);
      if (created.status === "completed" && created.artifact) {
        onResult(created.artifact);
        setState("idle");
      } else if (created.status === "failed") {
        setError(created.error_summary ?? "Podcast generation failed");
        setState("error");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Podcast generation failed");
      setState("error");
    }
  }

  return (
    <form className="canvas podcast-canvas" onSubmit={submit}>
      <div className="podcast-compose">
        <div className="podcast-script-column">
          <ScriptField
            label={t("podcast.script")}
            value={script}
            onChange={setScript}
            importable
            required
            rows={10}
            extraHeader={
              <select
                className="compact-select"
                value={scriptFormat}
                onChange={(event) => setScriptFormat(event.target.value as PodcastScriptFormat)}
                aria-label={t("podcast.scriptFormat")}
              >
                <option value="auto">Auto</option>
                <option value="speaker_colon">Speaker lines</option>
                <option value="markdown">Markdown</option>
                <option value="json">JSON</option>
                <option value="yaml">YAML</option>
              </select>
            }
            onImportFormat={(format) => setScriptFormat(podcastFormatForTextImport(format))}
          />
          <section className="card podcast-preview-card">
            <div className="card-header">
              <span className="card-label">{t("podcast.parsePreview")}</span>
              <span className="char-count">{t("common.chars", { count: parsed.segments.length })}</span>
            </div>
            <div className="podcast-preview-list">
              {parsed.errors.map((item, index) => (
                <Notice key={`${item.line ?? "all"}-${index}`} variant="error">
                  {item.line ? `L${item.line}: ` : ""}
                  {item.message}
                </Notice>
              ))}
              {parsed.segments.length === 0 && parsed.errors.length === 0 ? (
                <p className="field-hint">{t("podcast.noSegments")}</p>
              ) : null}
              {parsed.segments.slice(0, 20).map((segment, index) => (
                <div key={`${segment.line}-${index}`} className="podcast-segment-row">
                  <span>{segment.speakerName}</span>
                  <span>{segment.text}</span>
                  <span>{segment.pauseAfterMs} ms</span>
                </div>
              ))}
            </div>
          </section>
        </div>

        <section className="card podcast-speakers-card">
          <div className="card-header">
            <span className="card-label">{t("podcast.speakers")}</span>
          </div>
          <label className="field">
            <span className="field-title">{t("tts.model")}</span>
            <select value={selectedModel} onChange={(event) => onModelChange(event.target.value)}>
              {models.length === 0 ? <option value="">{t("tts.noCompatibleModels")}</option> : null}
              {models.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-title">{t("podcast.defaultPause")}</span>
            <input
              type="number"
              min={0}
              max={60000}
              value={defaultPauseMs}
              onChange={(event) => setDefaultPauseMs(Number(event.target.value))}
            />
          </label>
          {parsed.speakers.map((speaker) => (
            <label key={speaker.id} className="field">
              <span className="field-title">{speaker.name}</span>
              <select
                value={speakerVoices[speaker.id] ?? ""}
                onChange={(event) => setSpeakerVoices((current) => ({ ...current, [speaker.id]: event.target.value }))}
              >
                <option value="">{t("tts.voice")}</option>
                {voices.map((voice) => (
                  <option key={voice.id} value={voice.id}>
                    {voice.name || voice.id}
                  </option>
                ))}
              </select>
            </label>
          ))}
          {missingVoice ? <Notice variant="error">{t("podcast.missingVoice")}</Notice> : null}
          {job && state === "loading" ? (
            <p className="field-hint">
              {t("podcast.progress", {
                current: job.current_segment ?? 0,
                total: job.total_segments ?? 0,
                speaker: job.current_speaker ?? "",
              })}
            </p>
          ) : null}
        </section>
      </div>

      <div className="card action-card">
        {error ? <Notice variant="error">{error}</Notice> : null}
        <button className="primary-action" type="submit" disabled={state === "loading" || !canSubmit}>
          {state === "loading" ? (
            <>
              <span className="spinner" aria-hidden="true" />
              {t("podcast.generating")}
            </>
          ) : (
            t("podcast.generate")
          )}
        </button>
      </div>
    </form>
  );
}

function podcastFormatForTextImport(format: TextFormat): PodcastScriptFormat {
  return format === "markdown" ? "markdown" : "speaker_colon";
}
