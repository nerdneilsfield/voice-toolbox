import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { AdvancedSettings } from "./components/AdvancedSettings";
import { FullscreenTextEditor } from "./components/FullscreenTextEditor";
import { LanguageSwitcher } from "./components/LanguageSwitcher";
import { ThemeToggle } from "./components/ThemeToggle";
import { useProviderCatalog } from "./hooks/useProviderCatalog";
import { useI18n } from "./i18n";
import { selectDefaultVoice, selectModelForCapability } from "./lib/providerSelection";
import {
  Artifact,
  Provider,
  ProviderModel,
  TextFormat,
  Voice,
  cloneVoice,
  designVoice,
  getArtifacts,
  getVoices,
  normalizeText,
  synthesizeBuiltin,
  transcribe,
} from "./api";

type MainTab = "tts" | "asr";
type TtsMode = "builtin" | "design" | "clone";
type RequestState = "idle" | "loading" | "success" | "error";
type DownloadFormat = "source" | "wav" | "mp3" | "pcm" | "m4a" | "aac" | "flac" | "ogg" | "webm";

const INLINE_TAGS = ["(唱歌)", "(笑)", "(叹气)", "(停顿)", "[breath]", "[laughter]"];
const BASE64_LIMIT_BYTES = 10 * 1024 * 1024;
const AUDIO_ACCEPT = ".wav,.mp3,.flac,.m4a,.ogg,.webm,.aac,audio/*";

function App() {
  const { t } = useI18n();
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
  const [cloneReferenceText, setCloneReferenceText] = useState("");
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
  const [modelProviderId, setModelProviderId] = useState("");
  const [voiceProviderId, setVoiceProviderId] = useState("");
  const [history, setHistory] = useState<Artifact[]>([]);
  const [historyError, setHistoryError] = useState("");
  const historyMountedRef = useRef(true);

  useEffect(() => {
    historyMountedRef.current = true;
    return () => {
      historyMountedRef.current = false;
    };
  }, []);

  // useCallback with empty deps so the initial load effect and the post-submit
  // refresh share one stable identity and exhaustive-deps stays satisfied.
  const refreshHistory = useCallback(() => {
    return getArtifacts(20)
      .then((items) => {
        if (!historyMountedRef.current) return;
        setHistory(items);
        setHistoryError("");
      })
      .catch((err) => {
        if (!historyMountedRef.current) return;
        setHistoryError(err instanceof Error ? err.message : t("errors.failedToLoadHistory"));
      });
  }, [t]);

  useEffect(() => {
    void refreshHistory();
  }, [refreshHistory]);

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
    const providerChanged = modelProviderId !== selectedProviderId;
    setBuiltinModel((current) =>
      selectModelForCapability(selectedProvider, "tts.builtin", providerChanged ? null : current),
    );
    setDesignModel((current) =>
      selectModelForCapability(selectedProvider, "tts.design", providerChanged ? null : current),
    );
    setCloneModel((current) =>
      selectModelForCapability(selectedProvider, "tts.clone", providerChanged ? null : current),
    );
    setAsrModel((current) =>
      selectModelForCapability(selectedProvider, "asr.transcribe", providerChanged ? null : current),
    );
    setModelProviderId(selectedProviderId);
  }, [modelProviderId, selectedProviderId, selectedProvider]);

  useEffect(() => {
    const providerChanged = voiceProviderId !== selectedProviderId;
    setVoiceId((current) => selectDefaultVoice(selectedProvider, voices, providerChanged ? null : current) ?? "");
    setVoiceProviderId(selectedProviderId);
  }, [voiceProviderId, selectedProviderId, selectedProvider, voices]);

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
      setPreviewError(err instanceof Error ? err.message : t("errors.textPreviewFailed"));
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
      void refreshHistory();
    } catch (err) {
      setTtsError(err instanceof Error ? err.message : t("errors.ttsRequestFailed"));
      setTtsState("error");
    }
  }

  async function submitClone() {
    if (!cloneFile) {
      throw new Error(t("errors.cloneSampleRequired"));
    }
    if (!cloneConsent) {
      throw new Error(t("errors.cloneConsentRequired"));
    }
    const body = new FormData();
    body.set("provider_id", selectedProviderId);
    body.set("text", cloneText);
    body.set("text_format", textFormat);
    body.set("consent_confirmed", String(cloneConsent));
    body.set("sample", cloneFile);
    appendFormValue(body, "style_instruction", cloneStyle);
    appendFormValue(body, "clone_reference_text", cloneReferenceText);
    appendFormValue(body, "model", cloneModel);
    return cloneVoice(body);
  }

  async function submitAsr(event: FormEvent) {
    event.preventDefault();
    if (!asrFile) {
      setAsrError(t("errors.asrAudioRequired"));
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
      if (!transcriptResponse.ok) {
        throw new Error(t("errors.transcriptDownloadFailed", { status: transcriptResponse.status }));
      }
      setTranscript(await transcriptResponse.text());
      setAsrState("success");
      void refreshHistory();
    } catch (err) {
      setAsrError(err instanceof Error ? err.message : t("errors.asrRequestFailed"));
      setAsrState("error");
    }
  }

  async function selectHistoryItem(artifact: Artifact) {
    setTtsError("");
    setAsrError("");
    if (artifact.kind === "audio") {
      setTtsArtifact(artifact);
      setTtsState("success");
      setTab("tts");
      return;
    }
    setAsrArtifact(artifact);
    setTranscript("");
    setAsrState("loading");
    setTab("asr");
    try {
      // Plain fetch, not requestJson: the download endpoint returns the raw
      // transcript as text/plain, not JSON. requestJson expects a JSON body and
      // would throw on the non-JSON response.
      const response = await fetch(artifact.download_url);
      if (!response.ok) {
        throw new Error(t("errors.transcriptDownloadFailed", { status: response.status }));
      }
      setTranscript(await response.text());
      setAsrState("success");
    } catch (err) {
      setTranscript("");
      setAsrError(err instanceof Error ? err.message : t("errors.failedToLoadTranscript"));
      setAsrState("error");
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">V</div>
          <div>
            <h1 className="brand-title">Voice Toolbox</h1>
            <p className="brand-subtitle">{t("brand.subtitle")}</p>
          </div>
        </div>
        <div className="provider-strip" aria-live="polite">
          <label>
            <select
              className="select-input"
              aria-label={t("provider.selectLabel")}
              value={selectedProviderId}
              onChange={(event) => setSelectedProviderId(event.target.value)}
            >
              {providers.length === 0 ? <option value="">{t("provider.noProviders")}</option> : null}
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </select>
          </label>
          <KeyStatus provider={selectedProvider} loading={providersLoading} />
        </div>
        <div className="topbar-controls">
          <LanguageSwitcher />
          <ThemeToggle />
        </div>
      </header>

      <ProviderDetails provider={selectedProvider} />

      {globalError ? <div className="notice error">{globalError}</div> : null}

      <div className="workspace">
        <Sidebar
          activeMode={ttsMode}
          onModeChange={setTtsMode}
          tab={tab}
          onTabChange={setTab}
          supportsCapability={supportsCapability}
        />

        {tab === "tts" ? (
          <form className="canvas" onSubmit={submitTts}>
            {!activeTtsSupported ? <div className="notice error compact">{t("tts.unsupportedMode")}</div> : null}

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
                <div className="card">
                  <AdvancedSettings
                    label={t("tts.advanced")}
                    models={providerModels("tts.builtin")}
                    selectedModel={builtinModel}
                    onModelChange={setBuiltinModel}
                  />
                </div>
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
                <div className="card">
                  <AdvancedSettings
                    label={t("tts.advanced")}
                    models={providerModels("tts.design")}
                    selectedModel={designModel}
                    onModelChange={setDesignModel}
                  />
                </div>
              </>
            ) : null}

            {ttsMode === "clone" ? (
              <>
                <CloneControls
                  text={cloneText}
                  setText={setCloneText}
                  referenceText={cloneReferenceText}
                  setReferenceText={setCloneReferenceText}
                  style={cloneStyle}
                  setStyle={setCloneStyle}
                  file={cloneFile}
                  setFile={setCloneFile}
                  consent={cloneConsent}
                  setConsent={setCloneConsent}
                  base64Size={cloneBase64Size}
                  overLimit={cloneOverLimit}
                />
                <div className="card">
                  <AdvancedSettings
                    label={t("tts.advanced")}
                    models={providerModels("tts.clone")}
                    selectedModel={cloneModel}
                    onModelChange={setCloneModel}
                  />
                </div>
              </>
            ) : null}

            <div className="card">
              <div className="card-header">
                <ModelSummary
                  models={selectedProvider?.models ?? []}
                  selectedModel={activeTtsModel(ttsMode, builtinModel, designModel, cloneModel)}
                />
                <span className="format-pill">{expectedTtsOutputLabel(selectedProvider)}</span>
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
                    {t("tts.generating")}
                  </>
                ) : (
                  t("tts.generateVoice")
                )}
              </button>
            </div>
            {ttsArtifact || ttsState === "loading" ? <ResultPanel artifact={ttsArtifact} state={ttsState} /> : null}
          </form>
        ) : (
          <form className="canvas" onSubmit={submitAsr}>
            <div className="card">
              <div className="card-header">
                <span className="card-label">{t("asr.audio")}</span>
              </div>
              <label className="field">
                <span className="field-title">{t("asr.audioFile")}</span>
                <input
                  type="file"
                  accept={AUDIO_ACCEPT}
                  onChange={(event) => setAsrFile(event.target.files?.[0] ?? null)}
                  required
                />
              </label>
              <label className="field">
                <span className="field-title">{t("asr.language")}</span>
                <select value={asrLanguage} onChange={(event) => setAsrLanguage(event.target.value)}>
                  <option value="auto">{t("asr.languageOption.auto")}</option>
                  <option value="zh">{t("asr.languageOption.zh")}</option>
                  <option value="en">{t("asr.languageOption.en")}</option>
                </select>
              </label>
            </div>
            <div className="card">
              <AdvancedSettings
                label={t("tts.advanced")}
                models={providerModels("asr.transcribe")}
                selectedModel={asrModel}
                onModelChange={setAsrModel}
              />
            </div>
            <div className="card">
              <div className="card-header">
                <ModelSummary models={selectedProvider?.models ?? []} selectedModel={asrModel} />
                <span className="format-pill">{asrLanguage.toUpperCase()}</span>
              </div>
              {asrError ? <div className="notice error compact">{asrError}</div> : null}
              {!asrSupported ? <div className="notice error compact">{t("asr.unsupported")}</div> : null}
              <button
                className="primary-action"
                type="submit"
                disabled={asrState === "loading" || !providerReady || !asrSupported}
              >
                {asrState === "loading" ? (
                  <>
                    <span className="spinner" aria-hidden="true" />
                    {t("asr.transcribing")}
                  </>
                ) : (
                  t("asr.transcribe")
                )}
              </button>
            </div>
            {asrArtifact || asrState === "loading" ? (
              <TranscriptPanel artifact={asrArtifact} transcript={transcript} state={asrState} />
            ) : null}
          </form>
        )}

        <aside className="output-panel">
          <div role="status" aria-live="polite" className="sr-only">
            {t("common.historyItems", { count: history.length })}
          </div>
          {historyError ? <div className="notice error compact">{historyError}</div> : null}
          <HistoryPanel artifacts={history} providers={providers} onSelect={selectHistoryItem} />
        </aside>
      </div>
    </main>
  );
}

const TTS_MODES: { id: TtsMode; icon: string }[] = [
  { id: "builtin", icon: "🔊" },
  { id: "design", icon: "✨" },
  { id: "clone", icon: "🎙️" },
];

function Sidebar({
  activeMode,
  onModeChange,
  tab,
  onTabChange,
  supportsCapability,
}: {
  activeMode: TtsMode;
  onModeChange: (mode: TtsMode) => void;
  tab: MainTab;
  onTabChange: (tab: MainTab) => void;
  supportsCapability: (capability: string) => boolean;
}) {
  const { t } = useI18n();
  return (
    <nav className="sidebar" aria-label={t("nav.ariaSections")}>
      <div>
        <div className="sidebar-section">{t("nav.ttsSection")}</div>
        {TTS_MODES.map((mode) => {
          const supported = supportsCapability(ttsCapability(mode.id));
          return (
            <button
              key={mode.id}
              className={["nav-item", activeMode === mode.id && tab === "tts" ? "active" : ""]
                .filter(Boolean)
                .join(" ")}
              type="button"
              disabled={!supported}
              onClick={() => {
                onModeChange(mode.id);
                onTabChange("tts");
              }}
            >
              <span>{mode.icon}</span>
              <span>{t(`tts.mode.${mode.id}` as const)}</span>
            </button>
          );
        })}
      </div>
      <div>
        <div className="sidebar-section">{t("nav.asrSection")}</div>
        <button
          className={["nav-item", tab === "asr" ? "active" : ""].filter(Boolean).join(" ")}
          type="button"
          disabled={!supportsCapability("asr.transcribe")}
          onClick={() => onTabChange("asr")}
        >
          <span>📝</span>
          <span>{t("nav.transcribe")}</span>
        </button>
      </div>
    </nav>
  );
}

function KeyStatus({ provider, loading }: { provider: Provider | null; loading: boolean }) {
  const { t } = useI18n();
  if (loading) {
    return <span className="status-badge">{t("keyStatus.loading")}</span>;
  }
  if (!provider || provider.has_api_key === undefined) {
    return <span className="status-badge">{t("keyStatus.unavailable")}</span>;
  }
  if (provider.has_api_key) {
    return <span className="status-badge ok">{t("keyStatus.configured")}</span>;
  }
  return <span className="status-badge warn">{t("keyStatus.missing")}</span>;
}

function ProviderDetails({ provider }: { provider: Provider | null }) {
  const { t } = useI18n();
  if (!provider) {
    return null;
  }
  return (
    <section className="provider-details" aria-label={t("providerDetails.statusAria")}>
      <StatusItem label={t("providerDetails.env")} value={provider.api_key_env ?? t("providerDetails.na")} />
      <StatusItem
        label={t("providerDetails.key")}
        value={
          provider.api_key_preview ??
          (provider.has_api_key ? t("providerDetails.configured") : t("providerDetails.missing"))
        }
      />
      <StatusItem label={t("providerDetails.baseUrl")} value={provider.base_url ?? t("providerDetails.na")} />
      <StatusItem label={t("providerDetails.config")} value={provider.config_path_preview ?? t("providerDetails.na")} />
    </section>
  );
}

function StatusItem({ label, value }: { label: string; value: string }) {
  return (
    <span className="status-item">
      <span className="label">{label}</span>
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
  const { t } = useI18n();
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
    <>
      <div className="card">
        <div className="card-header">
          <span className="card-label">{t("tts.voice")}</span>
        </div>
        <label className="field">
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
          <span className="field-title">{t("tts.stylePrompt")}</span>
          <input
            value={style}
            onChange={(event) => setStyle(event.target.value)}
            placeholder={t("tts.stylePlaceholder")}
          />
        </label>
      </div>

      <div className="card">
        <CardHeader
          label={t("tts.script")}
          count={text.length}
          title={t("tts.script")}
          value={text}
          onApply={setText}
        />
        <textarea
          className="script-input"
          ref={textAreaRef}
          value={text}
          rows={6}
          onChange={(event) => setText(event.target.value)}
          required
        />
        <div className="tag-row">
          {INLINE_TAGS.map((tag) => (
            <button key={tag} className="chip" type="button" onClick={() => insertTag(tag)}>
              {tag}
            </button>
          ))}
          <input
            className="tag-input"
            value={customTag}
            onChange={(event) => setCustomTag(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                submitCustomTag();
              }
            }}
            placeholder={t("tts.customTagPlaceholder")}
          />
        </div>
      </div>
    </>
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
  const { t } = useI18n();
  return (
    <>
      <div className="card">
        <CardHeader
          label={t("tts.voiceDescription")}
          count={description.length}
          title={t("tts.voiceDescription")}
          value={description}
          onApply={setDescription}
          extra={
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
        <textarea
          className="script-input"
          value={description}
          rows={6}
          onChange={(event) => setDescription(event.target.value)}
          placeholder={t("tts.voiceDescriptionPlaceholder")}
          required
        />
      </div>
      <div className="card">
        <CardHeader
          label={t("tts.script")}
          count={text.length}
          optional={optimizePreview}
          title={t("tts.script")}
          value={text}
          onApply={setText}
        />
        <textarea
          className="script-input"
          value={text}
          rows={5}
          onChange={(event) => setText(event.target.value)}
          placeholder={t("tts.previewTextPlaceholder")}
          required={!optimizePreview}
        />
      </div>
    </>
  );
}

function CloneControls({
  text,
  setText,
  style,
  setStyle,
  referenceText,
  setReferenceText,
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
  referenceText: string;
  setReferenceText: (value: string) => void;
  file: File | null;
  setFile: (value: File | null) => void;
  consent: boolean;
  setConsent: (value: boolean) => void;
  base64Size: number;
  overLimit: boolean;
}) {
  const { t } = useI18n();
  return (
    <>
      <div className="card">
        <div className="card-header">
          <span className="card-label">{t("tts.referenceAudio")}</span>
        </div>
        <label className="field">
          <span className="field-title">{t("tts.cloneSample")}</span>
          <input
            type="file"
            accept={AUDIO_ACCEPT}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            required
          />
        </label>
        <p className={overLimit ? "notice error compact" : "notice compact"}>
          {t("clone.base64Limit")}{" "}
          {file ? t("clone.estimatedSize", { size: formatBytes(base64Size) }) : t("clone.chooseFile")}
        </p>
      </div>
      <div className="card">
        <CardHeader
          label={t("tts.sampleTranscript")}
          count={referenceText.length}
          optional
          title={t("tts.sampleTranscript")}
          value={referenceText}
          onApply={setReferenceText}
        />
        <textarea
          className="script-input"
          value={referenceText}
          rows={3}
          onChange={(event) => setReferenceText(event.target.value)}
          placeholder={t("tts.sampleTranscriptPlaceholder")}
        />
      </div>
      <div className="card">
        <CardHeader
          label={t("tts.script")}
          count={text.length}
          title={t("tts.script")}
          value={text}
          onApply={setText}
        />
        <textarea
          className="script-input"
          value={text}
          rows={6}
          onChange={(event) => setText(event.target.value)}
          required
        />
      </div>
      <div className="card">
        <div className="card-header">
          <span className="card-label">{t("tts.styleConsent")}</span>
        </div>
        <div className="two-col-fields">
          <label className="field">
            <span className="field-title">{t("tts.stylePrompt")}</span>
            <input
              value={style}
              onChange={(event) => setStyle(event.target.value)}
              placeholder={t("tts.stylePromptPlaceholder")}
            />
          </label>
          <label className="checkbox-line consent-checkbox">
            <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} required />
            <span>{t("tts.consentText")}</span>
          </label>
        </div>
      </div>
    </>
  );
}

function CardHeader({
  label,
  count,
  optional,
  title,
  value,
  onApply,
  extra,
}: {
  label: string;
  count?: number;
  optional?: boolean;
  title: string;
  value: string;
  onApply: (value: string) => void;
  extra?: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div className="card-header">
      <span className="card-label">{label}</span>
      <div className="card-actions">
        {extra}
        {optional ? (
          <span className="char-count">{t("tts.optional")}</span>
        ) : count !== undefined ? (
          <span className="char-count">{t("common.chars", { count })}</span>
        ) : null}
        <FullscreenTextEditor title={title} value={value} onApply={onApply} />
      </div>
    </div>
  );
}

function ModelSummary({ models, selectedModel }: { models: ProviderModel[]; selectedModel: string | null }) {
  const { t } = useI18n();
  const model = models.find((item) => item.id === selectedModel);
  if (!model) {
    return (
      <span className="meta-label">
        <span>{t("tts.model")}</span>
        <span>{t("tts.modelNone")}</span>
      </span>
    );
  }
  return (
    <span className="meta-label">
      <span>{t("tts.model")}</span>
      <span>{model.name || model.id}</span>
    </span>
  );
}

const FORMATS: DownloadFormat[] = ["source", "wav", "mp3", "pcm", "m4a", "aac", "flac", "ogg", "webm"];

function ResultPanel({ artifact, state }: { artifact: Artifact | null; state: RequestState }) {
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

function TranscriptPanel({
  artifact,
  transcript,
  state,
}: {
  artifact: Artifact | null;
  transcript: string;
  state: RequestState;
}) {
  const { t } = useI18n();
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
          </div>
          <pre className="transcript-viewer">{transcript || t("result.emptyTranscript")}</pre>
          <a className="download-link" href={artifact.download_url}>
            {t("result.downloadTranscript")}
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
  const { t } = useI18n();
  return (
    <div className="loading-state" aria-label={t("common.loading")}>
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
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KiB`;
  }
  const mib = bytes / (1024 * 1024);
  return `${mib.toFixed(2)} MiB`;
}

function expectedTtsOutputLabel(provider: Provider | null | undefined) {
  return provider?.type === "openrouter" || provider?.id === "openrouter" ? "MP3" : "WAV";
}

function audioLabel(mimeType: string) {
  if (mimeType === "audio/mpeg" || mimeType === "audio/mp3") {
    return "MP3";
  }
  if (mimeType === "audio/wav") {
    return "WAV";
  }
  if (mimeType === "audio/pcm" || mimeType === "audio/l16") {
    return "PCM";
  }
  if (mimeType === "audio/mp4" || mimeType === "audio/m4a") {
    return "M4A";
  }
  if (mimeType === "audio/aac") {
    return "AAC";
  }
  if (mimeType === "audio/flac") {
    return "FLAC";
  }
  if (mimeType === "audio/ogg") {
    return "OGG";
  }
  if (mimeType === "audio/webm") {
    return "WEBM";
  }
  return "audio";
}

function downloadUrlForFormat(url: string, format: DownloadFormat) {
  if (format === "source") {
    return url;
  }
  return `${url}?format=${encodeURIComponent(format)}`;
}

function HistoryPanel({
  artifacts,
  providers,
  onSelect,
}: {
  artifacts: Artifact[];
  providers: Provider[];
  onSelect: (artifact: Artifact) => void;
}) {
  const { t } = useI18n();
  const providerNames = useMemo(() => {
    const map = new Map<string, string>();
    providers.forEach((provider) => map.set(provider.id, provider.name));
    return map;
  }, [providers]);

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">{t("history.title")}</span>
        <span className="char-count">{t("history.last", { count: artifacts.length })}</span>
      </div>
      <div className="history-list">
        {artifacts.length === 0 ? (
          <p className="char-count">{t("history.empty")}</p>
        ) : (
          artifacts.map((artifact) => {
            const model = typeof artifact.metadata?.model === "string" ? artifact.metadata.model : null;
            const title = formatHistoryTitle(artifact, t);
            return (
              <div key={artifact.id} className="history-item">
                <div className="history-meta">
                  <div className="history-title-row">
                    <span className="history-title">{title}</span>
                  </div>
                  <span className="history-subtitle">
                    {providerNames.get(artifact.provider_id) ?? artifact.provider_id}
                    {model ? ` • ${model}` : null}
                  </span>
                  {artifact.preview ? <span className="history-preview">{artifact.preview}</span> : null}
                  <span className="history-time">{formatHistoryTime(artifact.created_at)}</span>
                </div>
                <button
                  className="btn btn-ghost"
                  type="button"
                  aria-label={t("history.loadAria", { title })}
                  onClick={() => onSelect(artifact)}
                >
                  {artifact.kind === "audio" ? t("history.play") : t("history.view")}
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function formatHistoryTitle(
  artifact: Artifact,
  t: (key: import("./i18n").TranslationKey, values?: Record<string, string | number>) => string,
): string {
  const op = artifact.operation ?? "unknown";
  const kind = artifact.kind ?? "unknown";
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

function formatHistoryTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

export default App;
