import type { ProviderOptionSpec, ProviderModel } from "../api";
import { useI18n } from "../i18n";
import type { ProviderOptionValues } from "../lib/providerOptions";
import { ProviderOptionsPanel } from "./ProviderOptionsPanel";

type AdvancedOptionsCardProps = {
  models: ProviderModel[];
  selectedModel: string | null;
  onModelChange: (value: string) => void;
  optionSpecs: ProviderOptionSpec[];
  optionValues: ProviderOptionValues;
  onOptionValuesChange: (values: ProviderOptionValues) => void;
  /** When set, render model + options inline (no collapsible). Used while the
   *  parent already owns its own collapsible boundary. */
  inline?: boolean;
};

/**
 * Model selector + provider options. Collapses only when it actually contains
 * something worth hiding (options). Previously this rendered an empty
 * "Provider options" <details> inside an "Advanced" <details> whenever the
 * provider had no options — a nested empty shell.
 */
export function AdvancedOptionsCard({
  models,
  selectedModel,
  onModelChange,
  optionSpecs,
  optionValues,
  onOptionValuesChange,
  inline,
}: AdvancedOptionsCardProps) {
  const { t } = useI18n();
  const hasModels = models.length > 0;
  const hasOptions = optionSpecs.length > 0;
  const hasModelsOnly = hasModels && !hasOptions;

  const body = (
    <>
      <label className="field">
        <span className="field-title">{t("tts.model")}</span>
        <select
          value={selectedModel ?? ""}
          onChange={(event) => onModelChange(event.target.value)}
          disabled={!hasModels}
        >
          {hasModels ? null : <option value="">{t("tts.noCompatibleModels")}</option>}
          {models.map((model) => (
            <option key={model.id} value={model.id}>
              {model.name || model.id}
            </option>
          ))}
        </select>
      </label>
      {hasOptions ? (
        <ProviderOptionsPanel
          specs={optionSpecs}
          values={optionValues}
          onChange={onOptionValuesChange}
          summaryLabel={t("providerOptions.summary")}
        />
      ) : null}
    </>
  );

  // Nothing to show at all.
  if (!hasModels && !hasOptions) {
    return null;
  }

  // Parent already provides a collapsible boundary, or it's just a model
  // selector with no options — render flat, no nested collapse.
  if (inline || hasModelsOnly) {
    return <div className="advanced-inline">{body}</div>;
  }

  return (
    <details className="advanced-settings">
      <summary className="card-label">
        <span>{t("tts.advanced")}</span>
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
      {body}
    </details>
  );
}
