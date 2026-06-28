import type { ProviderModel } from "../api";

type AdvancedSettingsProps = {
  label: string;
  models: ProviderModel[];
  selectedModel: string | null;
  onModelChange(modelId: string): void;
  disabled?: boolean;
};

export function AdvancedSettings({ label, models, selectedModel, onModelChange, disabled }: AdvancedSettingsProps) {
  const hasModels = models.length > 0;
  return (
    <details className="advanced-settings">
      <summary className="card-label">{label}</summary>
      <label className="field">
        <span className="field-title">Model</span>
        <select
          value={selectedModel ?? ""}
          onChange={(event) => onModelChange(event.target.value)}
          disabled={disabled || !hasModels}
        >
          {hasModels ? null : <option value="">No compatible models</option>}
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
