import type { Provider } from "../api";
import { useI18n } from "../i18n";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { ThemeToggle } from "./ThemeToggle";

export function Topbar({
  providers,
  selectedProviderId,
  setSelectedProviderId,
  selectedProvider,
  providersLoading,
}: {
  providers: Provider[];
  selectedProviderId: string;
  setSelectedProviderId: (value: string) => void;
  selectedProvider: Provider | null;
  providersLoading: boolean;
}) {
  const { t } = useI18n();
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark">V</div>
        <div>
          <h1 className="brand-title">{t("brand.title")}</h1>
          <p className="brand-subtitle">{t("brand.subtitle")}</p>
        </div>
      </div>
      <div className="topbar-controls">
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
        <LanguageSwitcher />
        <ThemeToggle />
      </div>
    </header>
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
