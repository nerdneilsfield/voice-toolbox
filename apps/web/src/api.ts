export type Capability = "tts.builtin" | "tts.design" | "tts.clone" | "asr.transcribe" | string;

export type TextFormat = "plain" | "markdown" | "auto";

export type ProviderModel = {
  id: string;
  name: string;
  capability?: string | null;
  note?: string | null;
  options?: ProviderOptionSpec[];
  transcript_capabilities?: TranscriptCapabilities | null;
};

export type TranscriptCapabilities = {
  timestamps?: boolean;
  speakers?: boolean;
  segments?: boolean;
};

export type ProviderOptionType = "boolean" | "integer" | "number" | "string" | "text" | "select" | "multiselect";

export type ProviderOptionValue = boolean | number | string | string[] | null;

export type ProviderOptionChoice = {
  value: string;
  label: string;
  description?: string | null;
};

export type ProviderOptionSpec = {
  key: string;
  label?: string | null;
  type?: ProviderOptionType | null;
  capability: string;
  description?: string | null;
  default?: ProviderOptionValue;
  choices?: ProviderOptionChoice[] | null;
  min_value?: number | null;
  max_value?: number | null;
  step?: number | null;
  placeholder?: string | null;
  required?: boolean | null;
  advanced?: boolean | null;
  provider_specific?: boolean | null;
  safe_metadata?: boolean | null;
  enabled?: boolean | null;
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
  options?: ProviderOptionSpec[];
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
  preview?: string;
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
  textFile?: File | null;
  textFormat: TextFormat;
  voiceId: string;
  styleInstruction?: string;
  model?: string;
  chunkingMode?: ChunkingMode;
  chunkMaxChars?: number;
  chunkSilenceMs?: number;
  providerOptions?: Record<string, unknown>;
};

export type DesignForm = {
  providerId: string;
  voiceDescription: string;
  textFormat: TextFormat;
  text?: string;
  textFile?: File | null;
  optimizeTextPreview: boolean;
  model?: string;
  providerOptions?: Record<string, unknown>;
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

export type ChunkingMode = "off" | "auto" | "force";

export type ASRChunkSessionCreate = {
  providerId: string;
  model?: string | null;
  language: string;
  sourceDurationMs: number;
  totalChunks: number;
  sourceFileName?: string | null;
  transcriptTimestamps?: boolean;
  transcriptSpeakers?: boolean;
  providerOptions?: Record<string, unknown>;
  signal?: AbortSignal;
};

export type ASRChunkSession = {
  session_id: string;
  browser_slice_formats: string[];
  backend_accept_formats: string[];
  max_chunks: number;
  expires_at: string;
};

export type ASRChunkUpload = {
  sessionId: string;
  file: Blob;
  fileName: string;
  chunkIndex: number;
  offsetMs: number;
  durationMs: number;
  signal?: AbortSignal;
};

export type ASRChunkUploadResponse = {
  session_id: string;
  received_chunks: number;
  total_chunks: number;
};

export type ASRChunkFinish = {
  sessionId: string;
  providerId?: string | null;
  model?: string | null;
  language?: string | null;
  transcriptTimestamps?: boolean;
  transcriptSpeakers?: boolean;
  providerOptions?: Record<string, unknown>;
  signal?: AbortSignal;
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
  if (form.textFile) {
    body.set("text_file", form.textFile);
  } else {
    body.set("text", form.text);
  }
  body.set("text_format", form.textFormat);
  body.set("voice_id", form.voiceId);
  appendOptional(body, "style_instruction", form.styleInstruction);
  appendOptional(body, "model", form.model);
  appendChunking(body, form);
  appendProviderOptions(body, form.providerOptions);
  return requestForm("/v1/tts/builtin", body);
}

export function designVoice(form: DesignForm): Promise<OperationResponse> {
  const body = new FormData();
  body.set("provider_id", form.providerId);
  body.set("voice_description", form.voiceDescription);
  body.set("text_format", form.textFormat);
  body.set("optimize_text_preview", String(form.optimizeTextPreview));
  if (form.textFile) {
    body.set("text_file", form.textFile);
  } else {
    appendOptional(body, "text", form.text);
  }
  appendOptional(body, "model", form.model);
  appendProviderOptions(body, form.providerOptions);
  return requestForm("/v1/tts/design", body);
}

export function cloneVoice(formData: FormData): Promise<OperationResponse> {
  return requestForm("/v1/tts/clone", formData);
}

export function transcribe(formData: FormData, signal?: AbortSignal): Promise<OperationResponse> {
  return requestForm("/v1/asr/transcribe", formData, signal);
}

export function createAsrChunkSession(form: ASRChunkSessionCreate): Promise<ASRChunkSession> {
  const body = new FormData();
  body.set("provider_id", form.providerId);
  body.set("language", form.language);
  body.set("source_duration_ms", String(form.sourceDurationMs));
  body.set("total_chunks", String(form.totalChunks));
  body.set("transcript_timestamps", String(Boolean(form.transcriptTimestamps)));
  body.set("transcript_speakers", String(Boolean(form.transcriptSpeakers)));
  appendOptional(body, "model", form.model);
  appendOptional(body, "source_file_name", form.sourceFileName);
  appendProviderOptions(body, form.providerOptions);
  return requestForm("/v1/asr/chunk-sessions", body, form.signal);
}

export function uploadAsrChunk(form: ASRChunkUpload): Promise<ASRChunkUploadResponse> {
  const body = new FormData();
  body.set("file", form.file, form.fileName);
  body.set("chunk_index", String(form.chunkIndex));
  body.set("offset_ms", String(form.offsetMs));
  body.set("duration_ms", String(form.durationMs));
  return requestForm(`/v1/asr/chunk-sessions/${encodeURIComponent(form.sessionId)}/chunks`, body, form.signal);
}

export function finishAsrChunkSession(form: ASRChunkFinish): Promise<OperationResponse> {
  const body = new FormData();
  appendOptional(body, "provider_id", form.providerId);
  appendOptional(body, "model", form.model);
  appendOptional(body, "language", form.language);
  if (form.transcriptTimestamps !== undefined) {
    body.set("transcript_timestamps", String(form.transcriptTimestamps));
  }
  if (form.transcriptSpeakers !== undefined) {
    body.set("transcript_speakers", String(form.transcriptSpeakers));
  }
  appendProviderOptions(body, form.providerOptions);
  return requestForm(`/v1/asr/chunk-sessions/${encodeURIComponent(form.sessionId)}/finish`, body, form.signal);
}

export async function deleteAsrChunkSession(sessionId: string, signal?: AbortSignal): Promise<void> {
  await requestJson<{ deleted: boolean }>(`/v1/asr/chunk-sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    signal,
  });
}

export async function getArtifacts(limit = 20): Promise<Artifact[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  const payload = await requestJson<{ artifacts: Artifact[] }>(`/v1/artifacts?${params}`);
  return payload.artifacts;
}

export function transcriptDownloadUrl(
  artifactId: string,
  format: "txt" | "srt" | "vtt" | "json",
  options: { timestamps?: boolean; speakers?: boolean } = {},
): string {
  const params = new URLSearchParams({ format });
  if (format === "txt") {
    params.set("timestamps", String(Boolean(options.timestamps)));
    params.set("speakers", String(Boolean(options.speakers)));
  }
  return `/v1/artifacts/${encodeURIComponent(artifactId)}/transcript?${params}`;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = init ? await fetch(url, init) : await fetch(url);
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

async function requestForm<T>(url: string, body: FormData, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    body,
    signal,
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

function appendProviderOptions(body: FormData, providerOptions?: Record<string, unknown>): void {
  if (providerOptions && Object.keys(providerOptions).length > 0) {
    body.set("provider_options", JSON.stringify(providerOptions));
  }
}

function appendChunking(body: FormData, form: Pick<BuiltinForm, "chunkingMode" | "chunkMaxChars" | "chunkSilenceMs">) {
  appendOptional(body, "chunking_mode", form.chunkingMode);
  if (form.chunkMaxChars !== undefined) {
    body.set("chunk_max_chars", String(form.chunkMaxChars));
  }
  if (form.chunkSilenceMs !== undefined) {
    body.set("chunk_silence_ms", String(form.chunkSilenceMs));
  }
}
