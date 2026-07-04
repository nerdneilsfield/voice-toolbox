import { useMemo } from "react";
import type { Artifact, Provider } from "../api";
import { useI18n } from "../i18n";
import { formatHistoryTitle } from "./historyTitle";

export function HistoryPanel({
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

function formatHistoryTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}
