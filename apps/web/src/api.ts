export type Capability = "tts.builtin" | "tts.design" | "tts.clone" | "asr.transcribe" | string;

export type TextFormat = "plain" | "markdown" | "auto";

export type ProviderModel = {
  id: string;
  name: string;
  capability?: string | null;
  note?: string | null;
};

export type Voice = {
  id: string;
  name: string;
  language?: string | null;
  gender?: string | null;
  note?: string | null;
};

export type ProviderDefaultModels = Partial<Record<"tts_builtin" | "tts_design" | "tts_clone" | "asr", string | null>>;

export type Provider = {
  id: string;
  name: string;
  type?: string;
  base_url?: string | null;
  api_key_env?: string | null;
  api_key_preview?: string | null;
  config_path_preview?: string;
  default_voice?: string | null;
  default_models?: ProviderDefaultModels;
  capabilities: Capability[];
  models: ProviderModel[];
  voices?: Voice[];
  has_api_key?: boolean;
};

export type Artifact = {
  id: string;
  kind: "audio" | "transcript";
  provider_id: string;
  operation: string;
  mime_type: string;
  created_at: string;
  metadata: Record<string, unknown>;
  download_url: string;
};

export type Operation = {
  operation_id: string;
  operation: string;
  status: "completed" | "failed";
  started_at: string;
  finished_at: string;
  artifact_ids: string[];
  error_summary?: string | null;
};

export type OperationResponse = {
  operation: Operation;
  artifact: Artifact;
};

export type BuiltinForm = {
  providerId: string;
  text: string;
  textFormat: TextFormat;
  voiceId: string;
  styleInstruction?: string;
  model?: string;
};

export type DesignForm = {
  providerId: string;
  voiceDescription: string;
  textFormat: TextFormat;
  text?: string;
  optimizeTextPreview: boolean;
  model?: string;
};

export type NormalizeRequest = {
  content: string;
  input_format: TextFormat;
  normalizer_id?: string | null;
  options?: Record<string, unknown>;
};

export type NormalizeResponse = {
  text: string;
  input_format: TextFormat;
  output_format: "plain";
  normalizer_id: string;
  changed: boolean;
  metadata: Record<string, unknown>;
};

export async function getProviders(): Promise<Provider[]> {
  const payload = await requestJson<{ providers: Provider[] }>("/v1/providers");
  return payload.providers;
}

export async function getVoices(providerId: string): Promise<Voice[]> {
  const payload = await requestJson<{ voices: Voice[] }>(`/v1/providers/${encodeURIComponent(providerId)}/voices`);
  return payload.voices;
}

export function normalizeText(request: NormalizeRequest): Promise<NormalizeResponse> {
  return requestJsonWithBody("/v1/normalize/text", request);
}

export function synthesizeBuiltin(form: BuiltinForm): Promise<OperationResponse> {
  const body = new FormData();
  body.set("provider_id", form.providerId);
  body.set("text", form.text);
  body.set("text_format", form.textFormat);
  body.set("voice_id", form.voiceId);
  appendOptional(body, "style_instruction", form.styleInstruction);
  appendOptional(body, "model", form.model);
  return requestForm("/v1/tts/builtin", body);
}

export function designVoice(form: DesignForm): Promise<OperationResponse> {
  const body = new FormData();
  body.set("provider_id", form.providerId);
  body.set("voice_description", form.voiceDescription);
  body.set("text_format", form.textFormat);
  body.set("optimize_text_preview", String(form.optimizeTextPreview));
  appendOptional(body, "text", form.text);
  appendOptional(body, "model", form.model);
  return requestForm("/v1/tts/design", body);
}

export function cloneVoice(formData: FormData): Promise<OperationResponse> {
  return requestForm("/v1/tts/clone", formData);
}

export function transcribe(formData: FormData): Promise<OperationResponse> {
  return requestForm("/v1/asr/transcribe", formData);
}

export async function getArtifacts(limit = 20): Promise<Artifact[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  const payload = await requestJson<{ artifacts: Artifact[] }>(`/v1/artifacts?${params}`);
  return payload.artifacts;
}

async function requestJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  return parseResponse<T>(response);
}

async function requestJsonWithBody<TResponse, TBody extends Record<string, unknown>>(
  url: string,
  body: TBody,
): Promise<TResponse> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseResponse<TResponse>(response);
}

async function requestForm<T>(url: string, body: FormData): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    body,
  });
  return parseResponse<T>(response);
}

async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    throw new Error(readApiError(payload, response.status));
  }
  return payload as T;
}

function readApiError(payload: unknown, status: number): string {
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  }
  if (typeof payload === "string" && payload.trim()) {
    return payload;
  }
  return `Request failed with status ${status}`;
}

function appendOptional(body: FormData, key: string, value?: string | null): void {
  const trimmed = value?.trim();
  if (trimmed) {
    body.set(key, trimmed);
  }
}
