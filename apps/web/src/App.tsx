import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Artifact,
  Provider,
  Voice,
  cloneVoice,
  designVoice,
  getProviders,
  getVoices,
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
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providersState, setProvidersState] = useState<RequestState>("loading");
  const [providerId, setProviderId] = useState("mimo");
  const [voices, setVoices] = useState<Voice[]>([]);
  const [voicesState, setVoicesState] = useState<RequestState>("idle");
  const [voiceId, setVoiceId] = useState("");
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
  const [error, setError] = useState("");
  const [ttsArtifact, setTtsArtifact] = useState<Artifact | null>(null);
  const [asrArtifact, setAsrArtifact] = useState<Artifact | null>(null);
  const [transcript, setTranscript] = useState("");
  const textAreaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    let ignore = false;
    setProvidersState("loading");
    getProviders()
      .then((items) => {
        if (ignore) {
          return;
        }
        setProviders(items);
        setProviderId((current) => items.find((provider) => provider.id === current)?.id ?? items[0]?.id ?? "mimo");
        setProvidersState("success");
      })
      .catch((err: Error) => {
        if (!ignore) {
          setError(err.message);
          setProvidersState("error");
        }
      });
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (!providerId) {
      return;
    }
    let ignore = false;
    setVoicesState("loading");
    getVoices(providerId)
      .then((items) => {
        if (ignore) {
          return;
        }
        setVoices(items);
        setVoiceId((current) => items.find((voice) => voice.id === current)?.id ?? items[0]?.id ?? "");
        setVoicesState("success");
      })
      .catch((err: Error) => {
        if (!ignore) {
          setVoices([]);
          setError(err.message);
          setVoicesState("error");
        }
      });
    return () => {
      ignore = true;
    };
  }, [providerId]);

  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.id === providerId) ?? providers[0],
    [providers, providerId],
  );
  const activeModels = useMemo(() => selectedProvider?.models ?? [], [selectedProvider]);
  const cloneBase64Size = useMemo(() => (cloneFile ? Math.ceil(cloneFile.size / 3) * 4 : 0), [cloneFile]);
  const cloneOverLimit = cloneBase64Size > BASE64_LIMIT_BYTES;

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

  async function submitTts(event: FormEvent) {
    event.preventDefault();
    setError("");
    setTtsState("loading");
    try {
      const result =
        ttsMode === "builtin"
          ? await synthesizeBuiltin({
              providerId,
              text: builtinText,
              voiceId,
              styleInstruction: builtinStyle,
            })
          : ttsMode === "design"
            ? await designVoice({
                providerId,
                voiceDescription: designDescription,
                text: designText,
                optimizeTextPreview: optimizePreview,
              })
            : await submitClone();
      setTtsArtifact(result.artifact);
      setTtsState("success");
    } catch (err) {
      setError(err instanceof Error ? err.message : "TTS request failed");
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
    body.set("provider_id", providerId);
    body.set("text", cloneText);
    body.set("consent_confirmed", String(cloneConsent));
    body.set("sample", cloneFile);
    if (cloneStyle.trim()) {
      body.set("style_instruction", cloneStyle.trim());
    }
    return cloneVoice(body);
  }

  async function submitAsr(event: FormEvent) {
    event.preventDefault();
    if (!asrFile) {
      setError("ASR audio file is required");
      setAsrState("error");
      return;
    }
    setError("");
    setAsrState("loading");
    setTranscript("");
    try {
      const body = new FormData();
      body.set("provider_id", providerId);
      body.set("language", asrLanguage);
      body.set("file", asrFile);
      const result = await transcribe(body);
      setAsrArtifact(result.artifact);
      const transcriptResponse = await fetch(result.artifact.download_url);
      setTranscript(await transcriptResponse.text());
      setAsrState("success");
    } catch (err) {
      setError(err instanceof Error ? err.message : "ASR request failed");
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
            <select value={providerId} onChange={(event) => setProviderId(event.target.value)}>
              {providers.length === 0 ? <option value="mimo">mimo</option> : null}
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </select>
          </label>
          <KeyStatus provider={selectedProvider} state={providersState} />
        </div>
      </header>

      <nav className="tabs" aria-label="Toolbox sections">
        <button className={tab === "tts" ? "active" : ""} type="button" onClick={() => setTab("tts")}>
          TTS
        </button>
        <button className={tab === "asr" ? "active" : ""} type="button" onClick={() => setTab("asr")}>
          ASR
        </button>
      </nav>

      {error ? <div className="notice error">{error}</div> : null}

      {tab === "tts" ? (
        <section className="tool-grid" aria-label="Text to speech toolbox">
          <form className="tool-panel" onSubmit={submitTts}>
            <fieldset className="segmented" aria-label="TTS mode">
              <button className={ttsMode === "builtin" ? "active" : ""} type="button" onClick={() => setTtsMode("builtin")}>
                Built-in
              </button>
              <button className={ttsMode === "design" ? "active" : ""} type="button" onClick={() => setTtsMode("design")}>
                Design
              </button>
              <button className={ttsMode === "clone" ? "active" : ""} type="button" onClick={() => setTtsMode("clone")}>
                Clone
              </button>
            </fieldset>

            {ttsMode === "builtin" ? (
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
            ) : null}

            {ttsMode === "design" ? (
              <DesignControls
                description={designDescription}
                setDescription={setDesignDescription}
                text={designText}
                setText={setDesignText}
                optimizePreview={optimizePreview}
                setOptimizePreview={setOptimizePreview}
              />
            ) : null}

            {ttsMode === "clone" ? (
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
            ) : null}

            <div className="meta-row">
              <span>Output format</span>
              <strong>wav</strong>
            </div>
            <ModelSummary models={activeModels} mode={ttsMode} />
            <button className="primary-action" type="submit" disabled={ttsState === "loading" || cloneOverLimit}>
              {ttsState === "loading" ? "Synthesizing..." : "Synthesize"}
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
            <ModelSummary models={activeModels} mode="asr" />
            <button className="primary-action" type="submit" disabled={asrState === "loading"}>
              {asrState === "loading" ? "Transcribing..." : "Transcribe"}
            </button>
          </form>

          <TranscriptPanel artifact={asrArtifact} transcript={transcript} state={asrState} />
        </section>
      )}
    </main>
  );
}

function KeyStatus({ provider, state }: { provider?: Provider; state: RequestState }) {
  if (state === "loading") {
    return <span className="key-status muted">Key status loading</span>;
  }
  if (!provider || provider.has_api_key === undefined) {
    return <span className="key-status muted">Key status unavailable</span>;
  }
  return <span className={provider.has_api_key ? "key-status ok" : "key-status warn"}>{provider.has_api_key ? "API key configured" : "API key missing"}</span>;
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
  textAreaRef: React.MutableRefObject<HTMLTextAreaElement | null>;
}) {
  return (
    <div className="field-stack">
      <label>
        Voice
        <select value={voiceId} onChange={(event) => setVoiceId(event.target.value)} disabled={voicesState === "loading"}>
          {voices.map((voice) => (
            <option key={voice.id} value={voice.id}>
              {voice.name || voice.id}
            </option>
          ))}
        </select>
      </label>
      <div>
        <div className="label-line">
          <span>Text</span>
          <div className="tag-row" aria-label="Insert audio tags">
            {INLINE_TAGS.map((tag) => (
              <button key={tag} type="button" onClick={() => insertTag(tag)}>
                {tag}
              </button>
            ))}
          </div>
        </div>
        <textarea ref={textAreaRef} value={text} rows={9} onChange={(event) => setText(event.target.value)} required />
      </div>
      <label>
        Style instruction
        <input
          value={style}
          onChange={(event) => setStyle(event.target.value)}
          placeholder="Natural-language delivery, emotion, pacing, or persona"
        />
      </label>
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
      <label>
        Voice design instruction
        <textarea
          value={description}
          rows={6}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Describe timbre, age, accent, energy, pace, and scene"
          required
        />
      </label>
      <label className="checkbox-line">
        <input type="checkbox" checked={optimizePreview} onChange={(event) => setOptimizePreview(event.target.checked)} />
        Optimize preview text
      </label>
      <label>
        Target text {optimizePreview ? <span className="muted">(optional)</span> : null}
        <textarea
          value={text}
          rows={5}
          onChange={(event) => setText(event.target.value)}
          placeholder="Preview text for generated voice"
          required={!optimizePreview}
        />
      </label>
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
      <label>
        Clone sample
        <input
          type="file"
          accept=".wav,.mp3,audio/wav,audio/mpeg,audio/mp3"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          required
        />
      </label>
      <p className={overLimit ? "notice error compact" : "notice compact"}>
        Base64 payload limit is 10 MiB. {file ? `Estimated base64 size: ${formatBytes(base64Size)}.` : "Choose wav or mp3."}
      </p>
      <label>
        Text
        <textarea value={text} rows={6} onChange={(event) => setText(event.target.value)} required />
      </label>
      <label>
        Style instruction
        <input
          value={style}
          onChange={(event) => setStyle(event.target.value)}
          placeholder="Natural-language delivery, emotion, pacing, or persona"
        />
      </label>
      <label className="checkbox-line">
        <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} required />
        I have permission to use this voice sample for synthesis.
      </label>
    </div>
  );
}

function ModelSummary({ models, mode }: { models: Provider["models"]; mode: TtsMode | "asr" }) {
  const capability = mode === "asr" ? "asr.transcribe" : `tts.${mode}`;
  const matching = models.filter((model) => model.capability === capability);
  if (matching.length === 0) {
    return null;
  }
  return (
    <div className="meta-row">
      <span>Model</span>
      <strong>{matching[0].name || matching[0].id}</strong>
    </div>
  );
}

function ResultPanel({ artifact, state }: { artifact: Artifact | null; state: RequestState }) {
  return (
    <aside className="result-panel">
      <h2>TTS artifact</h2>
      {state === "idle" ? <p className="muted">No audio generated yet.</p> : null}
      {state === "loading" ? <p className="muted">Waiting for provider...</p> : null}
      {artifact ? (
        <div className="artifact-block">
          <audio controls src={artifact.download_url} />
          <a className="download-link" href={artifact.download_url}>
            Download wav
          </a>
          <dl>
            <div>
              <dt>Artifact ID</dt>
              <dd>{artifact.id}</dd>
            </div>
            <div>
              <dt>MIME</dt>
              <dd>{artifact.mime_type}</dd>
            </div>
          </dl>
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
  return (
    <aside className="result-panel">
      <h2>Transcript</h2>
      {state === "idle" ? <p className="muted">No transcript generated yet.</p> : null}
      {state === "loading" ? <p className="muted">Waiting for provider...</p> : null}
      {artifact ? (
        <div className="artifact-block">
          <pre className="transcript-viewer">{transcript || "Transcript artifact returned."}</pre>
          <a className="download-link" href={artifact.download_url}>
            Download transcript
          </a>
        </div>
      ) : null}
    </aside>
  );
}

function formatBytes(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const mib = bytes / (1024 * 1024);
  return `${mib.toFixed(2)} MiB`;
}

export default App;
