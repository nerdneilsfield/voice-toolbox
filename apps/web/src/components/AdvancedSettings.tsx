import { useI18n } from "../i18n";
import type { ProviderModel } from "../api";

type AdvancedSettingsProps = {
  label: string;
  models: ProviderModel[];
  selectedModel: string | null;
  onModelChange(modelId: string): void;
  disabled?: boolean;
};

export function AdvancedSettings({ label, models, selectedModel, onModelChange, disabled }: AdvancedSettingsProps) {
  const { t } = useI18n();
  const hasModels = models.length > 0;
  return (
    <details className="advanced-settings">
      <summary className="card-label">
        <span>{label}</span>
        <svg className="advanced-chevron" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path
            d="M2 4l4 4 4-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </summary>
      <label className="field">
        <span className="field-title">{t("tts.model")}</span>
        <select
          value={selectedModel ?? ""}
          onChange={(event) => onModelChange(event.target.value)}
          disabled={disabled || !hasModels}
        >
          {hasModels ? null : <option value="">{t("tts.noCompatibleModels")}</option>}
          {models.map((model) => (
            <option key={model.id} value={model.id}>
              {model.name || model.id}
            </option>
          ))}
        </select>
      </label>
    </details>
  );
}
