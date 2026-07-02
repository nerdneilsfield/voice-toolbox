import type { Provider } from "../api";

export function providerRequiresApiKey(provider: Provider | null | undefined): boolean {
  if (!provider) {
    return false;
  }
  if (provider.requires_api_key === false) {
    return false;
  }
  return provider.has_api_key !== undefined || Boolean(provider.api_key_env);
}

export function providerHasMissingApiKey(provider: Provider | null | undefined): boolean {
  return providerRequiresApiKey(provider) && provider?.has_api_key === false;
}
