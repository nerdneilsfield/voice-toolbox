import { useEffect, useMemo, useState } from "react";
import { getProviders, type Provider } from "../api";

export function useProviderCatalog() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState("mimo");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const items = await getProviders();
      setProviders(items);
      setSelectedProviderId((current) => items.find((item) => item.id === current)?.id ?? items[0]?.id ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load providers");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.id === selectedProviderId) ?? providers[0] ?? null,
    [providers, selectedProviderId],
  );

  return { providers, selectedProvider, selectedProviderId, setSelectedProviderId, error, loading, refresh };
}
