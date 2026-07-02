import type { Provider } from "../api";
import { useI18n } from "../i18n";

/**
 * Provider connection details. Collapsed by default — it previously occupied a
 * full first-screen row mostly filled with "n/a". Highlighted automatically
 * when the API key is missing so the issue is obvious without the noise.
 */
export function ProviderDetails({ provider }: { provider: Provider | null }) {
  const { t } = useI18n();
  if (!provider) {
    return null;
  }
  const keyMissing = provider.has_api_key === false;
  return (
    <details className={`provider-details${keyMissing ? " key-missing" : ""}`} open={keyMissing}>
      <summary className="provider-details-summary">
        {t("providerDetails.statusAria")}
        {keyMissing ? <span className="status-badge warn">{t("keyStatus.missing")}</span> : null}
      </summary>
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
    </details>
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
