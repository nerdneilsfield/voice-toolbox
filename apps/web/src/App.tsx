import { useCallback, useEffect, useRef, useState } from "react";
import { AsrWorkspace } from "./components/AsrWorkspace";
import { HistoryPanel } from "./components/HistoryPanel";
import { PodcastWorkspace } from "./components/PodcastWorkspace";
import { ProviderDetails } from "./components/ProviderDetails";
import { ResultPanel } from "./components/ResultPanel";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import type { TtsMode } from "./components/TtsWorkspace";
import { TtsWorkspace } from "./components/TtsWorkspace";
import { useProviderCatalog } from "./hooks/useProviderCatalog";
import { useProviderSelection } from "./hooks/useProviderSelection";
import { useI18n } from "./i18n";
import type { Artifact, Voice } from "./api";
import { getArtifacts, getVoices } from "./api";
import { voicesForModel } from "./lib/providerSelection";
import type { MainTab } from "./types";

function ttsCapability(mode: TtsMode): string {
  return mode === "builtin" ? "tts.builtin" : mode === "design" ? "tts.design" : "tts.clone";
}

function App() {
  const { t } = useI18n();
  const {
    providers,
    selectedProvider,
    selectedProviderId,
    setSelectedProviderId,
    error: providerError,
  } = useProviderCatalog();
  const [tab, setTab] = useState<MainTab>("tts");
  const [ttsMode, setTtsMode] = useState<TtsMode>("builtin");

  const [voices, setVoices] = useState<Voice[]>([]);
  const [voicesError, setVoicesError] = useState("");
  const [history, setHistory] = useState<Artifact[]>([]);
  const [historyError, setHistoryError] = useState("");
  const historyMountedRef = useRef(true);

  const [ttsArtifact, setTtsArtifact] = useState<Artifact | null>(null);
  const [asrArtifact, setAsrArtifact] = useState<Artifact | null>(null);
  const [podcastArtifact, setPodcastArtifact] = useState<Artifact | null>(null);
  const [asrTranscript, setAsrTranscript] = useState("");
  const [ttsState, setTtsState] = useState<"idle" | "loading" | "error">("idle");
  const [asrState, setAsrState] = useState<"idle" | "loading" | "error">("idle");
  const [podcastState, setPodcastState] = useState<"idle" | "loading" | "error">("idle");

  const selection = useProviderSelection(selectedProvider, voices);

  useEffect(() => {
    historyMountedRef.current = true;
    return () => {
      historyMountedRef.current = false;
    };
  }, []);

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

  // Load voices when the provider changes; clear on switch.
  useEffect(() => {
    if (!selectedProviderId) {
      setVoices([]);
      return;
    }
    let ignore = false;
    setVoices([]);
    setVoicesError("");
    getVoices(selectedProviderId)
      .then((items) => {
        if (!ignore) setVoices(items);
      })
      .catch((err: Error) => {
        if (!ignore) {
          setVoices([]);
          setVoicesError(err.message);
        }
      });
    return () => {
      ignore = true;
    };
  }, [selectedProviderId]);

  // A5: switching provider invalidates previous results and the mode/model
  // derived from the old provider.
  const lastProviderId = useRef("");
  useEffect(() => {
    if (selectedProviderId && selectedProviderId !== lastProviderId.current && lastProviderId.current !== "") {
      setTtsArtifact(null);
      setAsrArtifact(null);
      setPodcastArtifact(null);
      setAsrTranscript("");
      setTtsState("idle");
      setAsrState("idle");
      setPodcastState("idle");
    }
    lastProviderId.current = selectedProviderId;
  }, [selectedProviderId]);

  // Fallback: if the active mode is unsupported by the new provider, pick one.
  const supportsCapability = (capability: string) => selectedProvider?.capabilities.includes(capability) ?? false;
  const activeTtsSupported = supportsCapability(ttsCapability(ttsMode));
  const asrSupported = supportsCapability("asr.transcribe");
  useEffect(() => {
    if (!selectedProvider || activeTtsSupported) return;
    const fallback = (["builtin", "design", "clone"] as const).find((mode) =>
      selectedProvider.capabilities.includes(ttsCapability(mode)),
    );
    if (fallback) setTtsMode(fallback);
  }, [activeTtsSupported, selectedProvider]);

  // Mode selection lives in App so the sidebar and the workspace agree, and so
  // history clicks can restore the matching mode (A4).
  const onModelChange = useCallback(
    (capability: "tts.builtin" | "tts.design" | "tts.clone" | "asr.transcribe", value: string) => {
      if (capability === "asr.transcribe") return; // ASR model handled by its workspace
      selection.setModel(
        capability === "tts.builtin" ? "builtin" : capability === "tts.design" ? "design" : "clone",
        value,
      );
    },
    [selection],
  );

  // A4: selecting a history item restores the ttsMode that produced it, so the
  // sidebar + workspace reflect the loaded artifact instead of stranding the
  // user in whatever mode was active.
  async function selectHistoryItem(artifact: Artifact) {
    if (artifact.kind === "audio") {
      if (artifact.operation === "podcast") {
        setPodcastArtifact(artifact);
        setPodcastState("idle");
        setTab("podcast");
        return;
      }
      const mode = String(artifact.metadata?.tts_mode ?? "builtin");
      if (mode === "builtin" || mode === "design" || mode === "clone") {
        setTtsMode(mode);
      }
      setTtsArtifact(artifact);
      setTtsState("idle");
      setTab("tts");
      return;
    }
    setAsrArtifact(artifact);
    setAsrState("loading");
    setTab("asr");
    try {
      const response = await fetch(artifact.download_url);
      if (!response.ok) throw new Error(t("errors.transcriptDownloadFailed", { status: response.status }));
      setAsrTranscript(await response.text());
      setAsrState("idle");
    } catch (err) {
      setAsrTranscript("");
      setAsrState("error");
      void err;
    }
  }

  const globalError = providerError || voicesError;
  const ttsVoices = voicesForModel(selectedProvider, voices, selection.models.builtin);

  return (
    <main className="app-shell">
      <Topbar
        providers={providers}
        selectedProviderId={selectedProviderId}
        setSelectedProviderId={setSelectedProviderId}
        selectedProvider={selectedProvider}
        providersLoading={false}
      />

      <ProviderDetails provider={selectedProvider} />

      {globalError ? <div className="notice error">{globalError}</div> : null}

      <div className={["workspace", tab === "podcast" ? "podcast-workspace-shell" : ""].filter(Boolean).join(" ")}>
        <Sidebar
          activeMode={ttsMode}
          onModeChange={setTtsMode}
          tab={tab}
          onTabChange={setTab}
          supportsCapability={supportsCapability}
        />

        {tab === "tts" ? (
          <TtsWorkspace
            provider={selectedProvider}
            providerId={selectedProviderId}
            models={selection.models}
            onModelChange={onModelChange}
            voices={ttsVoices}
            voiceId={selection.voiceId}
            onVoiceIdChange={selection.setVoiceId}
            ttsMode={ttsMode}
            ttsSupported={activeTtsSupported}
            onResult={(artifact) => {
              setTtsArtifact(artifact);
              setTtsState("idle");
              void refreshHistory();
            }}
            onModelSummary={() => {}}
          />
        ) : tab === "podcast" ? (
          <PodcastWorkspace
            provider={selectedProvider}
            providerId={selectedProviderId}
            model={selection.models.builtin}
            onModelChange={(value) => selection.setModel("builtin", value)}
            voices={ttsVoices}
            onResult={(artifact) => {
              setPodcastArtifact(artifact);
              setPodcastState("idle");
              if (artifact) void refreshHistory();
            }}
            onStateChange={setPodcastState}
          />
        ) : (
          <AsrWorkspace
            provider={selectedProvider}
            providerId={selectedProviderId}
            model={selection.models.asr}
            onModelChange={(value) => selection.setModel("asr", value)}
            asrSupported={asrSupported}
            artifact={asrArtifact}
            transcript={asrTranscript}
            resultState={asrState}
            onResult={(artifact, transcript) => {
              setAsrArtifact(artifact);
              setAsrTranscript(transcript);
              setAsrState(artifact ? "idle" : "loading");
              if (artifact) void refreshHistory();
            }}
          />
        )}

        <aside className="output-panel">
          <div role="status" aria-live="polite" className="sr-only">
            {t("common.historyItems", { count: history.length })}
          </div>
          {tab === "tts" && (ttsArtifact || ttsState === "loading") ? (
            <ResultPanel artifact={ttsArtifact} state={ttsState} />
          ) : null}
          {tab === "podcast" && (podcastArtifact || podcastState === "loading") ? (
            <ResultPanel artifact={podcastArtifact} state={podcastState} />
          ) : null}
          {historyError ? <div className="notice error compact">{historyError}</div> : null}
          <HistoryPanel artifacts={history} providers={providers} onSelect={selectHistoryItem} />
        </aside>
      </div>
    </main>
  );
}

export default App;
