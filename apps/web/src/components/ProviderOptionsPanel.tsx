import type { ProviderOptionSpec } from "../api";
import type { ProviderOptionValue } from "../api";
import type { ProviderOptionValues } from "../lib/providerOptions";
import { controlKindForOption } from "../lib/providerOptions";

type ProviderOptionsPanelProps = {
  specs: ProviderOptionSpec[];
  values: ProviderOptionValues;
  onChange(values: ProviderOptionValues): void;
  disabled?: boolean;
  summaryLabel?: string;
};

export function ProviderOptionsPanel({ specs, values, onChange, disabled, summaryLabel }: ProviderOptionsPanelProps) {
  if (specs.length === 0) {
    return null;
  }
  const primary = specs.filter((spec) => spec.advanced === false);
  const advanced = specs.filter((spec) => spec.advanced !== false);
  return (
    <div className="provider-options">
      {primary.map((spec) => (
        <ProviderOptionField
          key={spec.key}
          spec={spec}
          value={values[spec.key]}
          onValueChange={(value) => onChange({ ...values, [spec.key]: value })}
          disabled={disabled}
        />
      ))}
      {advanced.length > 0 ? (
        <details className="provider-option-details">
          <summary>{summaryLabel ?? "Provider options"}</summary>
          <div className="provider-option-grid">
            {advanced.map((spec) => (
              <ProviderOptionField
                key={spec.key}
                spec={spec}
                value={values[spec.key]}
                onValueChange={(value) => onChange({ ...values, [spec.key]: value })}
                disabled={disabled}
              />
            ))}
          </div>
        </details>
      ) : null}
    </div>
  );
}

function ProviderOptionField({
  spec,
  value,
  onValueChange,
  disabled,
}: {
  spec: ProviderOptionSpec;
  value: ProviderOptionValue | undefined;
  onValueChange(value: ProviderOptionValue): void;
  disabled?: boolean;
}) {
  const kind = controlKindForOption(spec);
  const title = spec.label ?? spec.key;
  const common = (
    <>
      <span className="field-title">
        {title}
        {spec.required ? <span aria-label="required"> *</span> : null}
      </span>
      {spec.description ? <span className="field-hint">{spec.description}</span> : null}
    </>
  );
  if (kind === "checkbox") {
    return (
      <label className="checkbox-line provider-option-field">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onValueChange(event.target.checked)}
          disabled={disabled}
        />
        <span>{title}</span>
      </label>
    );
  }
  if (kind === "textarea") {
    return (
      <label className="field provider-option-field">
        {common}
        <textarea
          value={typeof value === "string" ? value : ""}
          onChange={(event) => onValueChange(event.target.value)}
          placeholder={spec.placeholder ?? undefined}
          required={Boolean(spec.required)}
          rows={3}
          disabled={disabled}
        />
      </label>
    );
  }
  if (kind === "number") {
    return (
      <label className="field provider-option-field">
        {common}
        <input
          type="number"
          value={typeof value === "number" ? value : ""}
          onChange={(event) => onValueChange(event.target.value === "" ? null : Number(event.target.value))}
          min={spec.min_value ?? undefined}
          max={spec.max_value ?? undefined}
          step={spec.step ?? (spec.type === "integer" ? 1 : "any")}
          required={Boolean(spec.required)}
          disabled={disabled}
        />
      </label>
    );
  }
  if (kind === "select") {
    const choiceValues = new Set((spec.choices ?? []).map((choice) => choice.value));
    const current = typeof value === "string" && choiceValues.has(value) ? value : "";
    return (
      <label className="field provider-option-field">
        {common}
        <select value={current} onChange={(event) => onValueChange(event.target.value)} disabled={disabled}>
          <option value="" disabled={Boolean(spec.required)}>
            {spec.placeholder ?? "Select"}
          </option>
          {(spec.choices ?? []).map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label || choice.value}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (kind === "multiselect") {
    const choiceValues = new Set((spec.choices ?? []).map((choice) => choice.value));
    const current = Array.isArray(value) ? value.filter((item) => choiceValues.has(String(item))).map(String) : [];
    return (
      <label className="field provider-option-field">
        {common}
        <select
          multiple
          value={current}
          onChange={(event) => onValueChange(Array.from(event.target.selectedOptions).map((option) => option.value))}
          required={Boolean(spec.required)}
          disabled={disabled}
        >
          {(spec.choices ?? []).map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label || choice.value}
            </option>
          ))}
        </select>
      </label>
    );
  }
  return (
    <label className="field provider-option-field">
      {common}
      <input
        type="text"
        value={typeof value === "string" ? value : ""}
        onChange={(event) => onValueChange(event.target.value)}
        placeholder={spec.placeholder ?? undefined}
        required={Boolean(spec.required)}
        disabled={disabled}
      />
    </label>
  );
}
