import { useEffect, useRef, useState } from "react";
import type { ProviderOptionSpec } from "../api";
import { defaultOptionValues, sanitizeOptionValues, type ProviderOptionValues } from "../lib/providerOptions";

/**
 * Holds provider-option values for one (provider, capability) slot. When the
 * slot changes (provider or capability switched) the previous values are
 * discarded and fresh defaults are applied — the old implementation kept a
 * `providerId:capability` map that leaked stale values across providers.
 */
export function useProviderOptions(
  providerId: string,
  capability: string,
  specs: ProviderOptionSpec[],
): [ProviderOptionValues, (next: ProviderOptionValues) => void] {
  const [values, setValues] = useState<ProviderOptionValues>(() => defaultOptionValues(specs));
  const keyRef = useRef(`${providerId}:${capability}`);

  useEffect(() => {
    const key = `${providerId}:${capability}`;
    if (key !== keyRef.current) {
      // Different slot: drop everything and start from defaults.
      keyRef.current = key;
      setValues(defaultOptionValues(specs));
      return;
    }
    // Same slot, schema may have changed (model switch): keep values that are
    // still valid, then backfill any new defaults.
    setValues((current) => sanitizeOptionValues({ ...defaultOptionValues(specs), ...current }, specs));
  }, [providerId, capability, specs]);

  return [values, setValues];
}
