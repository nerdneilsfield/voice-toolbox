import { type FormEvent, useMemo, useRef, useState } from "react";
import type { Artifact, ChunkingMode, Provider, TextFormat } from "../api";
import { cloneVoice, designVoice, normalizeText, synthesizeBuiltin } from "../api";
import { useI18n } from "../i18n";
import { useProviderOptions } from "../hooks/useProviderOptions";
import {
  optionsForCapability,
  sanitizeOptionValues,
  selectedModel,
  validateOptionValues,
} from "../lib/providerOptions";
import { AdvancedOptionsCard } from "./AdvancedOptionsCard";
import { Notice } from "./Primitives";
import { ScriptField } from "./ScriptField";
import { TagRow } from "./TagRow";
import { TextTools } from "./TextTools";

export type TtsMode = "builtin" | "design" | "clone";

type TtsWorkspaceProps = {
  provider: Provider | null;
  providerId: string;
  models: { builtin: string | null; design: string | null; clone: string | null };
  onModelChange: (capability: "tts.builtin" | "tts.design" | "tts.clone", value: string) => void;
  voices: { id: string; name: string; note?: string | null }[];
  voiceId: string;
  onVoiceIdChange: (value: string) => void;
  ttsMode: TtsMode;
  ttsSupported: boolean;
  onResult: (artifact: Artifact | null) => void;
  onModelSummary: (label: string) => void;
};

const BASE64_LIMIT_BYTES = 10 * 1024 * 1024;

export function TtsWorkspace({
  provider,
  providerId,
  models,
  onModelChange,
  voices,
  voiceId,
  onVoiceIdChange,
  ttsMode,
  ttsSupported,
  onResult,
  onModelSummary,
}: TtsWorkspaceProps) {
  const { t } = useI18n();
  const [textFormat, setTextFormat] = useState<TextFormat>("plain");
  const [builtinText, setBuiltinText] = useState("你好，欢迎使用 Voice Toolbox。");
  const [builtinStyle, setBuiltinStyle] = useState("");
  const [designDescription, setDesignDescription] = useState("");
  const [designText, setDesignText] = useState("");
  const [optimizePreview, setOptimizePreview] = useState(true);
  const [cloneText, setCloneText] = useState("");
  const [cloneReferenceText, setCloneReferenceText] = useState("");
  const [cloneStyle, setCloneStyle] = useState("");
  const [cloneFile, setCloneFile] = useState<File | null>(null);
  const [cloneConsent, setCloneConsent] = useState(false);
  const [chunkingMode, setChunkingMode] = useState<ChunkingMode>("auto");
  const [chunkMaxChars, setChunkMaxChars] = useState(1500);
  const [chunkSilenceMs, setChunkSilenceMs] = useState(120);
  const [cleanedPreview, setCleanedPreview] = useState("");
  const [previewState, setPreviewState] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [previewError, setPreviewError] = useState("");
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState("");
  const builtinTextRef = useRef<HTMLTextAreaElement | null>(null);

  const builtinModelObj = selectedModel(provider, models.builtin);
  const designModelObj = selectedModel(provider, models.design);
  const cloneModelObj = selectedModel(provider, models.clone);

  const builtinSpecs = useMemo(
    () => optionsForCapability(provider, builtinModelObj, "tts.builtin"),
    [provider, builtinModelObj],
  );
  const designSpecs = useMemo(
    () => optionsForCapability(provider, designModelObj, "tts.design"),
    [provider, designModelObj],
  );
  const cloneSpecs = useMemo(
    () => optionsForCapability(provider, cloneModelObj, "tts.clone"),
    [provider, cloneModelObj],
  );

  const [builtinOptions, setBuiltinOptions] = useProviderOptions(providerId, "tts.builtin", builtinSpecs);
  const [designOptions, setDesignOptions] = useProviderOptions(providerId, "tts.design", designSpecs);
  const [cloneOptions, setCloneOptions] = useProviderOptions(providerId, "tts.clone", cloneSpecs);

  const activeSpecs = ttsMode === "builtin" ? builtinSpecs : ttsMode === "design" ? designSpecs : cloneSpecs;
  const activeOptions = ttsMode === "builtin" ? builtinOptions : ttsMode === "design" ? designOptions : cloneOptions;
  const activeModelId = ttsMode === "builtin" ? models.builtin : ttsMode === "design" ? models.design : models.clone;
  const activeModelLabel =
    (ttsMode === "builtin" ? builtinModelObj : ttsMode === "design" ? designModelObj : cloneModelObj)?.name ??
    activeModelId ??
    t("tts.modelNone");

  // Keep the parent's model summary line in sync with the active mode/model.
  useMemo(() => onModelSummary(activeModelLabel), [activeModelLabel, onModelSummary]);

  const cloneBase64Size = cloneFile ? Math.ceil(cloneFile.size / 3) * 4 : 0;
  const cloneOverLimit = cloneBase64Size > BASE64_LIMIT_BYTES;
  const selectedVoice = voices.find((voice) => voice.id === voiceId);

  function insertTag(tag: string) {
    const target = builtinTextRef.current;
    if (!target) {
      setBuiltinText((current) => `${current}${tag}`);
      return;
    }
    const start = target.selectionStart;
    const end = target.selectionEnd;
    const next = `${builtinText.slice(0, start)}${tag}${builtinText.slice(end)}`;
    setBuiltinText(next);
    requestAnimationFrame(() => {
      target.focus();
      target.setSelectionRange(start + tag.length, start + tag.length);
    });
  }

  function activeScriptText(): string {
    if (ttsMode === "builtin") return builtinText;
    if (ttsMode === "design") return designText;
    return cloneText;
  }

  function sanitizedOptionsOrThrow(): Record<string, unknown> {
    const sanitized = sanitizeOptionValues(activeOptions, activeSpecs);
    const errors = validateOptionValues(sanitized, activeSpecs);
    if (errors.length > 0) {
      throw new Error(errors.join("; "));
    }
    return sanitized as Record<string, unknown>;
  }

  async function previewCleaned() {
    setPreviewError("");
    setPreviewState("loading");
    setCleanedPreview("");
    try {
      const result = await normalizeText({ content: activeScriptText(), input_format: textFormat });
      setCleanedPreview(result.text);
      setPreviewState("success");
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : t("errors.textPreviewFailed"));
      setPreviewState("error");
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setState("loading");
    try {
      const providerOptions = sanitizedOptionsOrThrow();
      let result;
      if (ttsMode === "builtin") {
        result = await synthesizeBuiltin({
          providerId,
          text: builtinText,
          textFormat,
          voiceId,
          styleInstruction: builtinStyle,
          model: models.builtin ?? undefined,
          chunkingMode,
          chunkMaxChars,
          chunkSilenceMs,
          providerOptions,
        });
      } else if (ttsMode === "design") {
        result = await designVoice({
          providerId,
          voiceDescription: designDescription,
          textFormat,
          text: designText,
          optimizeTextPreview: optimizePreview,
          model: models.design ?? undefined,
          providerOptions,
        });
      } else {
        if (!cloneFile) throw new Error(t("errors.cloneSampleRequired"));
        if (!cloneConsent) throw new Error(t("errors.cloneConsentRequired"));
        const body = new FormData();
        body.set("provider_id", providerId);
        body.set("text", cloneText);
        body.set("text_format", textFormat);
        body.set("consent_confirmed", String(cloneConsent));
        body.set("sample", cloneFile);
        appendOptional(body, "style_instruction", cloneStyle);
        appendOptional(body, "clone_reference_text", cloneReferenceText);
        appendOptional(body, "model", models.clone);
        body.set("chunking_mode", chunkingMode);
        body.set("chunk_max_chars", String(chunkMaxChars));
        body.set("chunk_silence_ms", String(chunkSilenceMs));
        if (Object.keys(providerOptions).length > 0) {
          body.set("provider_options", JSON.stringify(providerOptions));
        }
        result = await cloneVoice(body);
      }
      onResult(result.artifact);
      setState("idle");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("errors.ttsRequestFailed"));
      setState("error");
    }
  }

  // Per-mode submit guard: clone needs both a sample and consent before the
  // button is even clickable (otherwise the user hits a server 422).
  const canSubmit =
    !!provider && ttsSupported && (ttsMode !== "clone" || (!!cloneFile && cloneConsent && !cloneOverLimit));

  return (
    <form className="canvas" onSubmit={submit}>
      {!ttsSupported ? <Notice variant="error">{t("tts.unsupportedMode")}</Notice> : null}

      <TextTools
        textFormat={textFormat}
        setTextFormat={setTextFormat}
        previewState={previewState}
        previewError={previewError}
        cleanedPreview={cleanedPreview}
        onPreview={previewCleaned}
        chunkingMode={chunkingMode}
        setChunkingMode={setChunkingMode}
        chunkMaxChars={chunkMaxChars}
        setChunkMaxChars={setChunkMaxChars}
        chunkSilenceMs={chunkSilenceMs}
        setChunkSilenceMs={setChunkSilenceMs}
      />

      {ttsMode === "builtin" ? (
        <>
          <section className="card">
            {voices.length > 0 ? (
              <>
                <div className="card-header">
                  <span className="card-label">{t("tts.voice")}</span>
                </div>
                <label className="field">
                  <select value={voiceId} onChange={(event) => onVoiceIdChange(event.target.value)}>
                    {voices.map((voice) => (
                      <option key={voice.id} value={voice.id}>
                        {voice.name || voice.id}
                      </option>
                    ))}
                  </select>
                  {selectedVoice?.note ? <span className="field-hint">{selectedVoice.note}</span> : null}
                </label>
              </>
            ) : null}
            <label className="field">
              <span className="field-title">{t("tts.stylePrompt")}</span>
              <input
                type="text"
                value={builtinStyle}
                onChange={(event) => setBuiltinStyle(event.target.value)}
                placeholder={t("tts.stylePlaceholder")}
              />
            </label>
          </section>
          <ScriptField
            label={t("tts.script")}
            value={builtinText}
            onChange={setBuiltinText}
            required
            importable
            onImportFormat={setTextFormat}
            textareaRef={builtinTextRef}
          />
          <div className="tag-card">
            <TagRow onInsert={insertTag} />
          </div>
          <AdvancedOptionsCard
            models={provider?.models.filter((m) => m.capability === "tts.builtin") ?? []}
            selectedModel={models.builtin}
            onModelChange={(value) => onModelChange("tts.builtin", value)}
            optionSpecs={builtinSpecs}
            optionValues={builtinOptions}
            onOptionValuesChange={setBuiltinOptions}
          />
        </>
      ) : null}

      {ttsMode === "design" ? (
        <>
          <ScriptField
            label={t("tts.voiceDescription")}
            value={designDescription}
            onChange={setDesignDescription}
            required
            extraHeader={
              <label className="switch-line">
                <input
                  type="checkbox"
                  checked={optimizePreview}
                  onChange={(event) => setOptimizePreview(event.target.checked)}
                />
                <span>{t("tts.autoOptimize")}</span>
              </label>
            }
          />
          <ScriptField
            label={t("tts.script")}
            value={designText}
            onChange={setDesignText}
            optional={optimizePreview}
            required={!optimizePreview}
            importable
            onImportFormat={setTextFormat}
          />
          <AdvancedOptionsCard
            models={provider?.models.filter((m) => m.capability === "tts.design") ?? []}
            selectedModel={models.design}
            onModelChange={(value) => onModelChange("tts.design", value)}
            optionSpecs={designSpecs}
            optionValues={designOptions}
            onOptionValuesChange={setDesignOptions}
          />
        </>
      ) : null}

      {ttsMode === "clone" ? (
        <>
          <section className="card">
            <div className="card-header">
              <span className="card-label">{t("tts.referenceAudio")}</span>
            </div>
            <label className="field">
              <span className="field-title">{t("tts.cloneSample")}</span>
              <input
                type="file"
                accept=".wav,.mp3,.flac,.m4a,.ogg,.webm,.aac,audio/*"
                onChange={(event) => setCloneFile(event.target.files?.[0] ?? null)}
                required
              />
            </label>
            <p className={cloneOverLimit ? "notice error compact" : "field-hint"}>
              {cloneOverLimit
                ? t("clone.estimatedSize", { size: formatBytes(cloneBase64Size) })
                : `${t("clone.base64Limit")} ${cloneFile ? t("clone.estimatedSize", { size: formatBytes(cloneBase64Size) }) : t("clone.chooseFile")}`}
            </p>
          </section>
          <ScriptField
            label={t("tts.sampleTranscript")}
            value={cloneReferenceText}
            onChange={setCloneReferenceText}
            optional
          />
          <ScriptField
            label={t("tts.script")}
            value={cloneText}
            onChange={setCloneText}
            required
            importable
            onImportFormat={setTextFormat}
          />
          <section className="card">
            <div className="card-header">
              <span className="card-label">{t("tts.styleConsent")}</span>
            </div>
            <div className="two-col-fields">
              <label className="field">
                <span className="field-title">{t("tts.stylePrompt")}</span>
                <input
                  type="text"
                  value={cloneStyle}
                  onChange={(event) => setCloneStyle(event.target.value)}
                  placeholder={t("tts.stylePromptPlaceholder")}
                />
              </label>
              <label className="checkbox-line consent-checkbox">
                <input
                  type="checkbox"
                  checked={cloneConsent}
                  onChange={(event) => setCloneConsent(event.target.checked)}
                  required
                />
                <span>{t("tts.consentText")}</span>
              </label>
            </div>
          </section>
          <AdvancedOptionsCard
            models={provider?.models.filter((m) => m.capability === "tts.clone") ?? []}
            selectedModel={models.clone}
            onModelChange={(value) => onModelChange("tts.clone", value)}
            optionSpecs={cloneSpecs}
            optionValues={cloneOptions}
            onOptionValuesChange={setCloneOptions}
          />
        </>
      ) : null}

      <div className="card action-card">
        {error ? <Notice variant="error">{error}</Notice> : null}
        <button className="primary-action" type="submit" disabled={state === "loading" || !canSubmit}>
          {state === "loading" ? (
            <>
              <span className="spinner" aria-hidden="true" />
              {t("tts.generating")}
            </>
          ) : (
            t("tts.generateVoice")
          )}
        </button>
      </div>
    </form>
  );
}

function appendOptional(body: FormData, key: string, value?: string | null) {
  const trimmed = value?.trim();
  if (trimmed) {
    body.set(key, trimmed);
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MiB`;
}
