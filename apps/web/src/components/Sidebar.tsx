import { useI18n } from "../i18n";
import type { TtsMode } from "./TtsWorkspace";

type MainTab = "tts" | "asr";

const TTS_MODES: { id: TtsMode; icon: string }[] = [
  { id: "builtin", icon: "🔊" },
  { id: "design", icon: "✨" },
  { id: "clone", icon: "🎙️" },
];

function ttsCapability(mode: TtsMode): string {
  return mode === "builtin" ? "tts.builtin" : mode === "design" ? "tts.design" : "tts.clone";
}

export function Sidebar({
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
