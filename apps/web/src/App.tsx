import { FormEvent, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { AdvancedSettings } from "./components/AdvancedSettings";
import { FullscreenTextEditor } from "./components/FullscreenTextEditor";
import { useProviderCatalog } from "./hooks/useProviderCatalog";
import { selectDefaultVoice, selectModelForCapability } from "./lib/providerSelection";
import {
  Artifact,
  Provider,
  ProviderModel,
  TextFormat,
  Voice,
  cloneVoice,
  designVoice,
  getVoices,
  normalizeText,
  synthesizeBuiltin,
  transcribe,
} from "./api";

type MainTab = "tts" | "asr";
type TtsMode = "builtin" | "design" | "clone";
type RequestState = "idle" | "loading" | "success" | "error";

const INLINE_TAGS = ["(唱歌)", "(笑)", "(叹气)", "(停顿)", "[breath]", "[laughter]"];
const BASE64_LIMIT_BYTES = 10 * 1024 * 1024;

function App() {
  const [tab, setTab] = useState<MainTab>("tts");
  const [ttsMode, setTtsMode] = useState<TtsMode>("builtin");
  const {
    providers,
    selectedProvider,
    selectedProviderId,
    setSelectedProviderId,
    error: providerError,
    loading: providersLoading,
  } = useProviderCatalog();
  const [voices, setVoices] = useState<Voice[]>([]);
  const [voicesState, setVoicesState] = useState<RequestState>("idle");
  const [voicesError, setVoicesError] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [builtinModel, setBuiltinModel] = useState<string | null>(null);
  const [designModel, setDesignModel] = useState<string | null>(null);
  const [cloneModel, setCloneModel] = useState<string | null>(null);
  const [asrModel, setAsrModel] = useState<string | null>(null);
  const [textFormat, setTextFormat] = useState<TextFormat>("plain");
  const [cleanedPreview, setCleanedPreview] = useState("");
  const [previewState, setPreviewState] = useState<RequestState>("idle");
  const [previewError, setPreviewError] = useState("");
  const [builtinText, setBuiltinText] = useState("你好，欢迎使用 Voice Toolbox。");
  const [builtinStyle, setBuiltinStyle] = useState("");
  const [designDescription, setDesignDescription] = useState("");
  const [designText, setDesignText] = useState("");
  const [optimizePreview, setOptimizePreview] = useState(true);
  const [cloneText, setCloneText] = useState("");
  const [cloneStyle, setCloneStyle] = useState("");
  const [cloneFile, setCloneFile] = useState<File | null>(null);
  const [cloneConsent, setCloneConsent] = useState(false);
  const [asrFile, setAsrFile] = useState<File | null>(null);
  const [asrLanguage, setAsrLanguage] = useState("auto");
  const [ttsState, setTtsState] = useState<RequestState>("idle");
  const [asrState, setAsrState] = useState<RequestState>("idle");
  const [ttsError, setTtsError] = useState("");
  const [asrError, setAsrError] = useState("");
  const [ttsArtifact, setTtsArtifact] = useState<Artifact | null>(null);
  const [asrArtifact, setAsrArtifact] = useState<Artifact | null>(null);
  const [transcript, setTranscript] = useState("");
  const textAreaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!selectedProviderId) {
      setVoices([]);
      setVoiceId("");
      return;
    }
    let ignore = false;
    setVoices([]);
    setVoiceId("");
    setVoicesError("");
    setVoicesState("loading");
    getVoices(selectedProviderId)
      .then((items) => {
        if (ignore) {
          return;
        }
        setVoices(items);
        setVoicesState("success");
      })
      .catch((err: Error) => {
        if (!ignore) {
          setVoices([]);
          setVoiceId("");
          setVoicesError(err.message);
          setVoicesState("error");
        }
      });
    return () => {
      ignore = true;
    };
  }, [selectedProviderId]);

  useEffect(() => {
    setBuiltinModel(selectModelForCapability(selectedProvider, "tts.builtin"));
    setDesignModel(selectModelForCapability(selectedProvider, "tts.design"));
    setCloneModel(selectModelForCapability(selectedProvider, "tts.clone"));
    setAsrModel(selectModelForCapability(selectedProvider, "asr.transcribe"));
  }, [selectedProviderId, selectedProvider]);

  useEffect(() => {
    setVoiceId(selectDefaultVoice(selectedProvider, voices) ?? "");
  }, [selectedProviderId, selectedProvider, voices]);

  useEffect(() => {
    setCleanedPreview("");
    setPreviewError("");
    setPreviewState("idle");
  }, [selectedProviderId, textFormat, ttsMode, builtinText, designText, cloneText]);

  const cloneBase64Size = useMemo(() => (cloneFile ? Math.ceil(cloneFile.size / 3) * 4 : 0), [cloneFile]);
  const cloneOverLimit = cloneBase64Size > BASE64_LIMIT_BYTES;
  const providerModels = (capability: string) =>
    selectedProvider?.models.filter((model) => model.capability === capability) ?? [];
  const globalError = providerError || voicesError;
  const providerReady = Boolean(selectedProvider);
  const supportsCapability = (capability: string) => selectedProvider?.capabilities.includes(capability) ?? false;
  const activeTtsCapability = ttsCapability(ttsMode);
  const activeTtsSupported = supportsCapability(activeTtsCapability);
  const asrSupported = supportsCapability("asr.transcribe");

  useEffect(() => {
    if (!selectedProvider || activeTtsSupported) {
      return;
    }
    const fallbackMode = (["builtin", "design", "clone"] as const).find((mode) =>
      selectedProvider.capabilities.includes(ttsCapability(mode)),
    );
    if (fallbackMode) {
      setTtsMode(fallbackMode);
    }
  }, [activeTtsSupported, selectedProvider, ttsMode]);

  function insertTag(tag: string) {
    const target = textAreaRef.current;
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

  function activeScriptText() {
    if (ttsMode === "builtin") {
      return builtinText;
    }
    if (ttsMode === "design") {
      return designText;
    }
    return cloneText;
  }

  async function previewCleanedText() {
    setPreviewError("");
    setPreviewState("loading");
    setCleanedPreview("");
    try {
      const result = await normalizeText({ content: activeScriptText(), input_format: textFormat });
      setCleanedPreview(result.text);
      setPreviewState("success");
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : "Text preview failed");
      setPreviewState("error");
    }
  }

  async function submitTts(event: FormEvent) {
    event.preventDefault();
    setTtsError("");
    setTtsState("loading");
    try {
      const result =
        ttsMode === "builtin"
          ? await synthesizeBuiltin({
              providerId: selectedProviderId,
              text: builtinText,
              textFormat,
              voiceId,
              styleInstruction: builtinStyle,
              model: builtinModel ?? undefined,
            })
          : ttsMode === "design"
            ? await designVoice({
                providerId: selectedProviderId,
                voiceDescription: designDescription,
                text: designText,
                textFormat,
                optimizeTextPreview: optimizePreview,
                model: designModel ?? undefined,
              })
            : await submitClone();
      setTtsArtifact(result.artifact);
      setTtsState("success");
    } catch (err) {
      setTtsError(err instanceof Error ? err.message : "TTS request failed");
      setTtsState("error");
    }
  }

  async function submitClone() {
    if (!cloneFile) {
      throw new Error("Clone sample file is required");
    }
    if (!cloneConsent) {
      throw new Error("Consent confirmation is required for voice clone");
    }
    const body = new FormData();
    body.set("provider_id", selectedProviderId);
    body.set("text", cloneText);
    body.set("text_format", textFormat);
    body.set("consent_confirmed", String(cloneConsent));
    body.set("sample", cloneFile);
    appendFormValue(body, "style_instruction", cloneStyle);
    appendFormValue(body, "model", cloneModel);
    return cloneVoice(body);
  }

  async function submitAsr(event: FormEvent) {
    event.preventDefault();
    if (!asrFile) {
      setAsrError("ASR audio file is required");
      setAsrState("error");
      return;
    }
    setAsrError("");
    setAsrState("loading");
    setTranscript("");
    try {
      const body = new FormData();
      body.set("provider_id", selectedProviderId);
      body.set("language", asrLanguage);
      body.set("file", asrFile);
      appendFormValue(body, "model", asrModel);
      const result = await transcribe(body);
      setAsrArtifact(result.artifact);
      const transcriptResponse = await fetch(result.artifact.download_url);
      setTranscript(await transcriptResponse.text());
      setAsrState("success");
    } catch (err) {
      setAsrError(err instanceof Error ? err.message : "ASR request failed");
      setAsrState("error");
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Voice Toolbox</h1>
          <p>TTS / ASR provider workbench</p>
        </div>
        <div className="provider-strip" aria-live="polite">
          <label>
            Provider
            <select value={selectedProviderId} onChange={(event) => setSelectedProviderId(event.target.value)}>
              {providers.length === 0 ? <option value="">No providers</option> : null}
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </select>
          </label>
          <KeyStatus provider={selectedProvider} loading={providersLoading} />
        </div>
      </header>

      <ProviderDetails provider={selectedProvider} />

      <nav className="tabs" aria-label="Toolbox sections">
        <button className={tab === "tts" ? "active" : ""} type="button" onClick={() => setTab("tts")}>
          TTS
        </button>
        <button className={tab === "asr" ? "active" : ""} type="button" onClick={() => setTab("asr")}>
          ASR
        </button>
      </nav>

      {globalError ? <div className="notice error">{globalError}</div> : null}

      {tab === "tts" ? (
        <section className="tool-grid" aria-label="Text to speech toolbox">
          <form className="tool-panel" onSubmit={submitTts}>
            <fieldset className="segmented" aria-label="TTS mode">
              <button
                className={ttsMode === "builtin" ? "active" : ""}
                type="button"
                disabled={!supportsCapability("tts.builtin")}
                onClick={() => setTtsMode("builtin")}
              >
                Built-in
              </button>
              <button
                className={ttsMode === "design" ? "active" : ""}
                type="button"
                disabled={!supportsCapability("tts.design")}
                onClick={() => setTtsMode("design")}
              >
                Design
              </button>
              <button
                className={ttsMode === "clone" ? "active" : ""}
                type="button"
                disabled={!supportsCapability("tts.clone")}
                onClick={() => setTtsMode("clone")}
              >
                Clone
              </button>
            </fieldset>
            {!activeTtsSupported ? (
              <div className="notice error compact">Selected provider does not support this TTS mode.</div>
            ) : null}

            <TextTools
              textFormat={textFormat}
              setTextFormat={setTextFormat}
              previewState={previewState}
              previewError={previewError}
              cleanedPreview={cleanedPreview}
              onPreview={previewCleanedText}
            />

            {ttsMode === "builtin" ? (
              <>
                <BuiltinControls
                  voices={voices}
                  voicesState={voicesState}
                  voiceId={voiceId}
                  setVoiceId={setVoiceId}
                  text={builtinText}
                  setText={setBuiltinText}
                  style={builtinStyle}
                  setStyle={setBuiltinStyle}
                  insertTag={insertTag}
                  textAreaRef={textAreaRef}
                />
                <AdvancedSettings
                  label="Advanced"
                  models={providerModels("tts.builtin")}
                  selectedModel={builtinModel}
                  onModelChange={setBuiltinModel}
                />
              </>
            ) : null}

            {ttsMode === "design" ? (
              <>
                <DesignControls
                  description={designDescription}
                  setDescription={setDesignDescription}
                  text={designText}
                  setText={setDesignText}
                  optimizePreview={optimizePreview}
                  setOptimizePreview={setOptimizePreview}
                />
                <AdvancedSettings
                  label="Advanced"
                  models={providerModels("tts.design")}
                  selectedModel={designModel}
                  onModelChange={setDesignModel}
                />
              </>
            ) : null}

            {ttsMode === "clone" ? (
              <>
                <CloneControls
                  text={cloneText}
                  setText={setCloneText}
                  style={cloneStyle}
                  setStyle={setCloneStyle}
                  file={cloneFile}
                  setFile={setCloneFile}
                  consent={cloneConsent}
                  setConsent={setCloneConsent}
                  base64Size={cloneBase64Size}
                  overLimit={cloneOverLimit}
                />
                <AdvancedSettings
                  label="Advanced"
                  models={providerModels("tts.clone")}
                  selectedModel={cloneModel}
                  onModelChange={setCloneModel}
                />
              </>
            ) : null}

            <div className="meta-row">
              <ModelSummary
                models={selectedProvider?.models ?? []}
                selectedModel={activeTtsModel(ttsMode, builtinModel, designModel, cloneModel)}
              />
              <span className="format-pill">WAV</span>
            </div>
            {ttsError ? <div className="notice error compact">{ttsError}</div> : null}
            <button
              className="primary-action"
              type="submit"
              disabled={ttsState === "loading" || cloneOverLimit || !providerReady || !activeTtsSupported}
            >
              {ttsState === "loading" ? (
                <>
                  <span className="spinner" aria-hidden="true" />
                  Generating...
                </>
              ) : (
                "Generate voice"
              )}
            </button>
          </form>

          <ResultPanel artifact={ttsArtifact} state={ttsState} />
        </section>
      ) : (
        <section className="tool-grid" aria-label="Speech to text toolbox">
          <form className="tool-panel" onSubmit={submitAsr}>
            <label>
              Audio file
              <input
                type="file"
                accept=".wav,.mp3,audio/wav,audio/mpeg,audio/mp3"
                onChange={(event) => setAsrFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <label>
              Language
              <select value={asrLanguage} onChange={(event) => setAsrLanguage(event.target.value)}>
                <option value="auto">auto</option>
                <option value="zh">zh</option>
                <option value="en">en</option>
              </select>
            </label>
            <AdvancedSettings
              label="Advanced"
              models={providerModels("asr.transcribe")}
              selectedModel={asrModel}
              onModelChange={setAsrModel}
            />
            <div className="meta-row">
              <ModelSummary models={selectedProvider?.models ?? []} selectedModel={asrModel} />
              <span className="format-pill">{asrLanguage.toUpperCase()}</span>
            </div>
            {asrError ? <div className="notice error compact">{asrError}</div> : null}
            {!asrSupported ? <div className="notice error compact">Selected provider does not support ASR.</div> : null}
            <button
              className="primary-action"
              type="submit"
              disabled={asrState === "loading" || !providerReady || !asrSupported}
            >
              {asrState === "loading" ? (
                <>
                  <span className="spinner" aria-hidden="true" />
                  Transcribing...
                </>
              ) : (
                "Transcribe"
              )}
            </button>
          </form>

          <TranscriptPanel artifact={asrArtifact} transcript={transcript} state={asrState} />
        </section>
      )}
    </main>
  );
}

function KeyStatus({ provider, loading }: { provider: Provider | null; loading: boolean }) {
  if (loading) {
    return <span className="key-status muted">Key status loading</span>;
  }
  if (!provider || provider.has_api_key === undefined) {
    return <span className="key-status muted">Key status unavailable</span>;
  }
  return (
    <span className={provider.has_api_key ? "key-status ok" : "key-status warn"}>
      {provider.has_api_key ? "API key configured" : "API key missing"}
    </span>
  );
}

function ProviderDetails({ provider }: { provider: Provider | null }) {
  if (!provider) {
    return null;
  }
  return (
    <section className="provider-details" aria-label="Provider status">
      <StatusItem label="Env" value={provider.api_key_env ?? "n/a"} />
      <StatusItem label="Key" value={provider.api_key_preview ?? (provider.has_api_key ? "configured" : "missing")} />
      <StatusItem label="Base URL" value={provider.base_url ?? "n/a"} />
      <StatusItem label="Config" value={provider.config_path_preview ?? "n/a"} />
    </section>
  );
}

function StatusItem({ label, value }: { label: string; value: string }) {
  return (
    <span className="status-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </span>
  );
}

function TextTools({
  textFormat,
  setTextFormat,
  previewState,
  previewError,
  cleanedPreview,
  onPreview,
}: {
  textFormat: TextFormat;
  setTextFormat: (value: TextFormat) => void;
  previewState: RequestState;
  previewError: string;
  cleanedPreview: string;
  onPreview: () => void;
}) {
  return (
    <section className="text-tools">
      <label>
        Text format
        <select value={textFormat} onChange={(event) => setTextFormat(event.target.value as TextFormat)}>
          <option value="plain">plain</option>
          <option value="markdown">markdown</option>
          <option value="auto">auto</option>
        </select>
      </label>
      <button className="secondary-action" type="button" onClick={onPreview} disabled={previewState === "loading"}>
        {previewState === "loading" ? "Previewing..." : "Preview cleaned text"}
      </button>
      {previewError ? <div className="notice error compact">{previewError}</div> : null}
      {cleanedPreview ? <pre className="cleaned-preview">{cleanedPreview}</pre> : null}
    </section>
  );
}

function BuiltinControls({
  voices,
  voicesState,
  voiceId,
  setVoiceId,
  text,
  setText,
  style,
  setStyle,
  insertTag,
  textAreaRef,
}: {
  voices: Voice[];
  voicesState: RequestState;
  voiceId: string;
  setVoiceId: (value: string) => void;
  text: string;
  setText: (value: string) => void;
  style: string;
  setStyle: (value: string) => void;
  insertTag: (tag: string) => void;
  textAreaRef: MutableRefObject<HTMLTextAreaElement | null>;
}) {
  const [customTag, setCustomTag] = useState("");
  const selectedVoice = voices.find((voice) => voice.id === voiceId);
  function submitCustomTag() {
    const trimmed = customTag.trim();
    if (!trimmed) {
      return;
    }
    const normalized = /^[([]/.test(trimmed) ? trimmed : `(${trimmed})`;
    insertTag(normalized);
    setCustomTag("");
  }

  return (
    <div className="field-stack">
      <div className="field-grid">
        <label className="field">
          <span className="field-title">Voice</span>
          <select
            value={voiceId}
            onChange={(event) => setVoiceId(event.target.value)}
            disabled={voicesState === "loading"}
          >
            {voices.map((voice) => (
              <option key={voice.id} value={voice.id}>
                {voice.name || voice.id}
              </option>
            ))}
          </select>
          {selectedVoice?.note ? <span className="field-hint">{selectedVoice.note}</span> : null}
        </label>
        <label className="field">
          <span className="field-title">Style prompt</span>
          <input
            value={style}
            onChange={(event) => setStyle(event.target.value)}
            placeholder="Delivery, emotion, pacing, persona"
          />
        </label>
      </div>
      <section className="field">
        <div className="section-heading">
          <span>Script</span>
          <TextEditorActions title="Script" value={text} onApply={setText} count={text.length} />
        </div>
        <div className="tag-panel" aria-label="Insert audio tags">
          <div className="tag-row">
            {INLINE_TAGS.map((tag) => (
              <button key={tag} type="button" onClick={() => insertTag(tag)}>
                {tag}
              </button>
            ))}
          </div>
          <div className="custom-tag">
            <input
              value={customTag}
              onChange={(event) => setCustomTag(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  submitCustomTag();
                }
              }}
              placeholder="Custom tag"
            />
            <button type="button" onClick={submitCustomTag}>
              Insert
            </button>
          </div>
        </div>
        <textarea
          className="script-input"
          ref={textAreaRef}
          value={text}
          rows={6}
          onChange={(event) => setText(event.target.value)}
          required
        />
      </section>
    </div>
  );
}

function DesignControls({
  description,
  setDescription,
  text,
  setText,
  optimizePreview,
  setOptimizePreview,
}: {
  description: string;
  setDescription: (value: string) => void;
  text: string;
  setText: (value: string) => void;
  optimizePreview: boolean;
  setOptimizePreview: (value: boolean) => void;
}) {
  return (
    <div className="field-stack">
      <section className="field">
        <div className="section-heading">
          <span>Voice persona</span>
          <span className="switch-line">
            <input
              type="checkbox"
              checked={optimizePreview}
              onChange={(event) => setOptimizePreview(event.target.checked)}
            />
            <span>Auto-optimize</span>
          </span>
        </div>
        <textarea
          className="script-input"
          value={description}
          rows={6}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Describe timbre, age, accent, energy, pace, and scene"
          required
        />
        <TextEditorActions
          title="Voice persona"
          value={description}
          onApply={setDescription}
          count={description.length}
        />
      </section>
      <section className="field">
        <div className="section-heading">
          <span>Script</span>
          <TextEditorActions
            title="Script"
            value={text}
            onApply={setText}
            count={text.length}
            optional={optimizePreview}
          />
        </div>
        <textarea
          className="script-input"
          value={text}
          rows={5}
          onChange={(event) => setText(event.target.value)}
          placeholder="Preview text for generated voice"
          required={!optimizePreview}
        />
      </section>
    </div>
  );
}

function CloneControls({
  text,
  setText,
  style,
  setStyle,
  file,
  setFile,
  consent,
  setConsent,
  base64Size,
  overLimit,
}: {
  text: string;
  setText: (value: string) => void;
  style: string;
  setStyle: (value: string) => void;
  file: File | null;
  setFile: (value: File | null) => void;
  consent: boolean;
  setConsent: (value: boolean) => void;
  base64Size: number;
  overLimit: boolean;
}) {
  return (
    <div className="field-stack">
      <label className="field">
        <span className="field-title">Clone sample</span>
        <input
          type="file"
          accept=".wav,.mp3,audio/wav,audio/mpeg,audio/mp3"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          required
        />
      </label>
      <p className={overLimit ? "notice error compact" : "notice compact"}>
        Base64 payload limit is 10 MiB.{" "}
        {file ? `Estimated base64 size: ${formatBytes(base64Size)}.` : "Choose wav or mp3."}
      </p>
      <section className="field">
        <div className="section-heading">
          <span>Script</span>
          <TextEditorActions title="Script" value={text} onApply={setText} count={text.length} />
        </div>
        <textarea
          className="script-input"
          value={text}
          rows={6}
          onChange={(event) => setText(event.target.value)}
          required
        />
      </section>
      <label className="field">
        <span className="field-title">Style prompt</span>
        <input
          value={style}
          onChange={(event) => setStyle(event.target.value)}
          placeholder="Natural-language delivery, emotion, pacing, or persona"
        />
      </label>
      <label className="checkbox-line">
        <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} required />I
        have permission to use this voice sample for synthesis.
      </label>
    </div>
  );
}

function TextEditorActions({
  title,
  value,
  onApply,
  count,
  optional,
}: {
  title: string;
  value: string;
  onApply: (value: string) => void;
  count: number;
  optional?: boolean;
}) {
  return (
    <span className="editor-actions">
      <span>{optional ? "Optional" : `${count} chars`}</span>
      <FullscreenTextEditor title={title} value={value} onApply={onApply} />
    </span>
  );
}

function ModelSummary({ models, selectedModel }: { models: ProviderModel[]; selectedModel: string | null }) {
  const model = models.find((item) => item.id === selectedModel);
  if (!model) {
    return <span className="model-chip muted">No model selected</span>;
  }
  return (
    <span className="model-chip">
      <span>Model</span>
      <strong>{model.name || model.id}</strong>
    </span>
  );
}

function ResultPanel({ artifact, state }: { artifact: Artifact | null; state: RequestState }) {
  return (
    <aside className="result-panel">
      <div className="result-heading">
        <h2>Output</h2>
        {artifact ? <span className="format-pill">Audio</span> : null}
      </div>
      {state === "idle" ? <EmptyState title="Ready for audio" /> : null}
      {state === "loading" ? <LoadingState lines={3} /> : null}
      {artifact ? (
        <div className="artifact-block">
          <audio className="audio-player" controls src={artifact.download_url} />
          <div className="result-actions">
            <a className="download-link" href={artifact.download_url}>
              Download WAV
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

function TranscriptPanel({
  artifact,
  transcript,
  state,
}: {
  artifact: Artifact | null;
  transcript: string;
  state: RequestState;
}) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  async function copyTranscript() {
    if (!transcript.trim()) {
      return;
    }
    try {
      await navigator.clipboard.writeText(transcript);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 1400);
    } catch {
      setCopyState("failed");
      window.setTimeout(() => setCopyState("idle"), 1400);
    }
  }

  return (
    <aside className="result-panel">
      <div className="result-heading">
        <h2>Transcript</h2>
        {artifact ? <span className="format-pill">{transcript.length} chars</span> : null}
      </div>
      {state === "idle" ? <EmptyState title="Ready for transcript" /> : null}
      {state === "loading" ? <LoadingState lines={4} /> : null}
      {artifact ? (
        <div className="artifact-block">
          <div className="transcript-toolbar">
            <button type="button" onClick={copyTranscript} disabled={!transcript.trim()}>
              {copyState === "copied" ? "Copied" : copyState === "failed" ? "Copy failed" : "Copy"}
            </button>
          </div>
          <pre className="transcript-viewer">{transcript || "Transcript artifact returned."}</pre>
          <a className="download-link" href={artifact.download_url}>
            Download transcript
          </a>
        </div>
      ) : null}
    </aside>
  );
}

function EmptyState({ title }: { title: string }) {
  return (
    <div className="empty-state">
      <div className="waveform" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
        <span />
      </div>
      <p>{title}</p>
    </div>
  );
}

function LoadingState({ lines }: { lines: number }) {
  return (
    <div className="loading-state" aria-label="Loading">
      {Array.from({ length: lines }).map((_, index) => (
        <span key={index} />
      ))}
    </div>
  );
}

function activeTtsModel(
  mode: TtsMode,
  builtinModel: string | null,
  designModel: string | null,
  cloneModel: string | null,
) {
  if (mode === "builtin") {
    return builtinModel;
  }
  if (mode === "design") {
    return designModel;
  }
  return cloneModel;
}

function ttsCapability(mode: TtsMode) {
  if (mode === "builtin") {
    return "tts.builtin";
  }
  if (mode === "design") {
    return "tts.design";
  }
  return "tts.clone";
}

function appendFormValue(body: FormData, key: string, value?: string | null) {
  const trimmed = value?.trim();
  if (trimmed) {
    body.set(key, trimmed);
  }
}

function shortId(id: string) {
  if (id.length <= 18) {
    return id;
  }
  return `${id.slice(0, 10)}...${id.slice(-6)}`;
}

function formatBytes(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const mib = bytes / (1024 * 1024);
  return `${mib.toFixed(2)} MiB`;
}

export default App;
