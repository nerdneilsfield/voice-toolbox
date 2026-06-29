import type { Provider, ProviderModel, ProviderOptionSpec, ProviderOptionValue } from "../api";

export type ProviderOptionValues = Record<string, ProviderOptionValue>;

export function optionsForCapability(
  provider: Provider | null | undefined,
  model: ProviderModel | null | undefined,
  capability: string,
): ProviderOptionSpec[] {
  const merged = new Map<string, ProviderOptionSpec>();
  const order: string[] = [];
  for (const option of provider?.options ?? []) {
    if (option.capability !== capability || option.enabled === false || !option.type) {
      continue;
    }
    merged.set(option.key, normalizeSpec(option));
    order.push(option.key);
  }
  for (const option of model?.options ?? []) {
    if (option.capability !== capability) {
      continue;
    }
    if (option.enabled === false) {
      merged.delete(option.key);
      continue;
    }
    const current = merged.get(option.key);
    if (current) {
      merged.set(option.key, normalizeSpec({ ...current, ...definedFields(option) }));
    } else if (option.type) {
      merged.set(option.key, normalizeSpec(option));
      order.push(option.key);
    }
  }
  return order.map((key) => merged.get(key)).filter((option): option is ProviderOptionSpec => Boolean(option));
}

export function defaultOptionValues(specs: ProviderOptionSpec[]): ProviderOptionValues {
  const values: ProviderOptionValues = {};
  for (const spec of specs) {
    if (spec.default !== undefined && spec.default !== null) {
      values[spec.key] = spec.default;
    }
  }
  return values;
}

export function sanitizeOptionValues(values: ProviderOptionValues, specs: ProviderOptionSpec[]): ProviderOptionValues {
  const byKey = new Map(specs.map((spec) => [spec.key, spec]));
  const sanitized: ProviderOptionValues = {};
  for (const [key, value] of Object.entries(values)) {
    const spec = byKey.get(key);
    if (!spec || value === null || value === "" || value === undefined) {
      continue;
    }
    const coerced = coerceOptionValue(spec, value);
    if (validateOptionValues({ [key]: coerced }, [spec]).length === 0) {
      sanitized[key] = coerced;
    }
  }
  for (const spec of specs) {
    if (sanitized[spec.key] === undefined && spec.default !== undefined && spec.default !== null) {
      const coercedDefault = coerceOptionValue(spec, spec.default);
      if (validateOptionValues({ [spec.key]: coercedDefault }, [spec]).length === 0) {
        sanitized[spec.key] = coercedDefault;
      }
    }
  }
  return sanitized;
}

export function validateOptionValues(values: ProviderOptionValues, specs: ProviderOptionSpec[]): string[] {
  const errors: string[] = [];
  const byKey = new Map(specs.map((spec) => [spec.key, spec]));
  for (const [key, value] of Object.entries(values)) {
    const spec = byKey.get(key);
    if (!spec) {
      errors.push(`${key} is not allowed`);
      continue;
    }
    const choiceValues = new Set((spec.choices ?? []).map((choice) => choice.value));
    if (spec.type === "select" && typeof value === "string" && !choiceValues.has(value)) {
      errors.push(`${key} must be one of the configured choices`);
    }
    if (
      spec.type === "multiselect" &&
      (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !choiceValues.has(item)))
    ) {
      errors.push(`${key} must be one of the configured choices`);
    }
    if (spec.type === "integer" || spec.type === "number") {
      if (typeof value !== "number" || !Number.isFinite(value)) {
        errors.push(`${key} must be a finite number`);
        continue;
      }
      if (spec.type === "integer" && !Number.isInteger(value)) {
        errors.push(`${key} must be an integer`);
        continue;
      }
      if (spec.min_value !== null && spec.min_value !== undefined && value < spec.min_value) {
        errors.push(`${key} is below minimum`);
      }
      if (spec.max_value !== null && spec.max_value !== undefined && value > spec.max_value) {
        errors.push(`${key} is above maximum`);
      }
    }
  }
  for (const spec of specs) {
    if (spec.required && (values[spec.key] === undefined || values[spec.key] === null || values[spec.key] === "")) {
      errors.push(`${spec.key} is required`);
    }
  }
  return errors;
}

export function controlKindForOption(spec: ProviderOptionSpec): string {
  if (spec.type === "text") return "textarea";
  if (spec.type === "boolean") return "checkbox";
  if (spec.type === "integer" || spec.type === "number") return "number";
  if (spec.type === "select") return "select";
  if (spec.type === "multiselect") return "multiselect";
  return "input";
}

export function selectedModel(provider: Provider | null | undefined, modelId: string | null | undefined) {
  return provider?.models.find((model) => model.id === modelId) ?? null;
}

function normalizeSpec(spec: ProviderOptionSpec): ProviderOptionSpec {
  return {
    ...spec,
    label: spec.label ?? spec.key,
    choices: spec.choices ?? [],
    advanced: spec.advanced ?? true,
    required: spec.required ?? false,
    enabled: spec.enabled ?? true,
  };
}

function definedFields(spec: ProviderOptionSpec): Partial<ProviderOptionSpec> {
  return Object.fromEntries(Object.entries(spec).filter(([, value]) => value !== null && value !== undefined));
}

function coerceOptionValue(spec: ProviderOptionSpec, value: ProviderOptionValue): ProviderOptionValue {
  if (spec.type === "integer") {
    return typeof value === "number" ? value : Number(value);
  }
  if (spec.type === "number") {
    return typeof value === "number" ? value : Number(value);
  }
  if (spec.type === "boolean") {
    return Boolean(value);
  }
  if (spec.type === "multiselect") {
    return Array.isArray(value) ? value : [String(value)];
  }
  return value;
}
