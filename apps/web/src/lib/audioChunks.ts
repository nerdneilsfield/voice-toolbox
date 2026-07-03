export type BrowserAudioChunk = {
  blob: Blob;
  offsetMs: number;
  durationMs: number;
  fileName: string;
};

export type WavInfo = {
  durationMs: number;
  sampleRate: number;
};

const MAX_PROVIDER_BASE64_BYTES = 10 * 1024 * 1024;
const MAX_PROVIDER_RAW_BYTES = Math.floor(MAX_PROVIDER_BASE64_BYTES / 4) * 3;
const WAV_HEADER_BYTES = 44;

export async function inspectWavFile(file: File): Promise<WavInfo> {
  const buffer = await file.arrayBuffer();
  return inspectWavBuffer(buffer);
}

export async function sliceWavFile(
  file: File,
  {
    targetSeconds,
    overlapMs,
  }: {
    targetSeconds: number;
    overlapMs: number;
  },
): Promise<{ chunks: BrowserAudioChunk[]; sourceDurationMs: number }> {
  const buffer = await file.arrayBuffer();
  if (!isWavBuffer(buffer)) {
    const wavBuffer = await decodeAudioFileToWav(buffer);
    return sliceParsedWavFile(wavBuffer, parseWav(wavBuffer), file, { targetSeconds, overlapMs });
  }
  const wav = parseWav(buffer);
  return sliceParsedWavFile(buffer, wav, file, { targetSeconds, overlapMs });
}

function sliceParsedWavFile(
  buffer: ArrayBuffer,
  wav: ParsedWav,
  file: File,
  {
    targetSeconds,
    overlapMs,
  }: {
    targetSeconds: number;
    overlapMs: number;
  },
): { chunks: BrowserAudioChunk[]; sourceDurationMs: number } {
  const bytesPerMs = wav.byteRate / 1000 || 1;
  const requestedChunkMs = Math.max(1000, targetSeconds * 1000);
  if (overlapMs >= requestedChunkMs / 2) {
    throw new Error("ASR chunk overlap must be less than half of chunk duration.");
  }
  const chunkMs = providerLimitedChunkMs(wav, requestedChunkMs);
  if (overlapMs >= chunkMs / 2) {
    throw new Error("ASR chunk payload limit requires smaller chunk duration or overlap.");
  }
  const strideMs = Math.max(1, chunkMs - Math.max(0, overlapMs));
  const chunks: BrowserAudioChunk[] = [];
  let offsetMs = 0;
  while (offsetMs < wav.durationMs) {
    const durationMs = Math.min(chunkMs, wav.durationMs - offsetMs);
    const start = wav.dataOffset + alignBlock(Math.floor(offsetMs * bytesPerMs), wav.blockAlign);
    const length = alignBlock(Math.ceil(durationMs * bytesPerMs), wav.blockAlign);
    const end = Math.min(wav.dataOffset + wav.dataSize, start + length);
    const payload = new Uint8Array(buffer.slice(start, end));
    chunks.push({
      blob: new Blob([buildWav(payload, wav)], { type: "audio/wav" }),
      offsetMs,
      durationMs: Math.round(((end - start) / wav.byteRate) * 1000),
      fileName: `${baseName(file.name)}.${chunks.length}.wav`,
    });
    offsetMs += strideMs;
  }
  return { chunks, sourceDurationMs: Math.round(wav.durationMs) };
}

async function decodeAudioFileToWav(buffer: ArrayBuffer): Promise<ArrayBuffer> {
  const AudioContextCtor =
    globalThis.AudioContext ??
    (globalThis as typeof globalThis & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AudioContextCtor) {
    throw new Error("Browser chunking requires WAV input or browser audio decoding support.");
  }
  const context = new AudioContextCtor();
  try {
    const audioBuffer = await context.decodeAudioData(buffer.slice(0));
    return audioBufferToWav(audioBuffer);
  } finally {
    await context.close().catch(() => undefined);
  }
}

function audioBufferToWav(audioBuffer: AudioBuffer): ArrayBuffer {
  const channels = Math.max(1, audioBuffer.numberOfChannels);
  const bitsPerSample = 16;
  const bytesPerSample = bitsPerSample / 8;
  const blockAlign = channels * bytesPerSample;
  const byteRate = audioBuffer.sampleRate * blockAlign;
  const frames = audioBuffer.length;
  const payload = new Uint8Array(frames * blockAlign);
  const view = new DataView(payload.buffer);
  const channelData = Array.from({ length: channels }, (_, channel) => audioBuffer.getChannelData(channel));

  for (let frame = 0; frame < frames; frame += 1) {
    for (let channel = 0; channel < channels; channel += 1) {
      const sample = Math.max(-1, Math.min(1, channelData[channel][frame] ?? 0));
      const value = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      view.setInt16((frame * channels + channel) * bytesPerSample, value, true);
    }
  }

  return buildWav(payload, {
    audioFormat: 1,
    channels,
    sampleRate: audioBuffer.sampleRate,
    byteRate,
    blockAlign,
    bitsPerSample,
    dataOffset: WAV_HEADER_BYTES,
    dataSize: payload.byteLength,
    durationMs: audioBuffer.duration * 1000,
  });
}

function isWavBuffer(buffer: ArrayBuffer): boolean {
  if (buffer.byteLength < 12) return false;
  const view = new DataView(buffer);
  return readAscii(view, 0, 4) === "RIFF" && readAscii(view, 8, 4) === "WAVE";
}

function inspectWavBuffer(buffer: ArrayBuffer): WavInfo {
  const wav = parseWav(buffer);
  return { durationMs: Math.round(wav.durationMs), sampleRate: wav.sampleRate };
}

type ParsedWav = {
  audioFormat: number;
  channels: number;
  sampleRate: number;
  byteRate: number;
  blockAlign: number;
  bitsPerSample: number;
  dataOffset: number;
  dataSize: number;
  durationMs: number;
};

function parseWav(buffer: ArrayBuffer): ParsedWav {
  const view = new DataView(buffer);
  if (readAscii(view, 0, 4) !== "RIFF" || readAscii(view, 8, 4) !== "WAVE") {
    throw new Error("Browser chunking currently requires WAV input.");
  }
  let offset = 12;
  let fmt: Partial<ParsedWav> | null = null;
  let dataOffset = 0;
  let dataSize = 0;
  while (offset + 8 <= view.byteLength) {
    const id = readAscii(view, offset, 4);
    const size = view.getUint32(offset + 4, true);
    const payloadOffset = offset + 8;
    if (id === "fmt ") {
      const audioFormat = view.getUint16(payloadOffset, true);
      const channels = view.getUint16(payloadOffset + 2, true);
      const sampleRate = view.getUint32(payloadOffset + 4, true);
      const byteRate = view.getUint32(payloadOffset + 8, true);
      const blockAlign = view.getUint16(payloadOffset + 12, true);
      const bitsPerSample = view.getUint16(payloadOffset + 14, true);
      fmt = { audioFormat, channels, sampleRate, byteRate, blockAlign, bitsPerSample };
    } else if (id === "data") {
      dataOffset = payloadOffset;
      dataSize = size;
    }
    offset = payloadOffset + size + (size % 2);
  }
  if (!fmt || !dataOffset || !dataSize || !fmt.byteRate || !fmt.blockAlign) {
    throw new Error("Invalid WAV file.");
  }
  const channels = fmt.channels ?? 1;
  const sampleRate = fmt.sampleRate ?? 24000;
  const bitsPerSample = fmt.bitsPerSample ?? 16;
  const blockAlign = fmt.blockAlign;
  const byteRate = fmt.byteRate;
  if (fmt.audioFormat !== 1) {
    throw new Error("Browser chunking currently supports PCM WAV input only.");
  }
  if (channels <= 0 || sampleRate <= 0 || bitsPerSample <= 0 || bitsPerSample % 8 !== 0) {
    throw new Error("Invalid PCM WAV file.");
  }
  if (blockAlign !== channels * (bitsPerSample / 8) || byteRate !== sampleRate * blockAlign) {
    throw new Error("Invalid PCM WAV file.");
  }
  return {
    audioFormat: fmt.audioFormat,
    channels,
    sampleRate,
    byteRate,
    blockAlign,
    bitsPerSample,
    dataOffset,
    dataSize,
    durationMs: (dataSize / fmt.byteRate) * 1000,
  };
}

function buildWav(payload: Uint8Array, source: ParsedWav): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + payload.byteLength);
  const view = new DataView(buffer);
  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + payload.byteLength, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, source.audioFormat, true);
  view.setUint16(22, source.channels, true);
  view.setUint32(24, source.sampleRate, true);
  view.setUint32(28, source.byteRate, true);
  view.setUint16(32, source.blockAlign, true);
  view.setUint16(34, source.bitsPerSample, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, payload.byteLength, true);
  new Uint8Array(buffer, 44).set(payload);
  return buffer;
}

function providerLimitedChunkMs(wav: ParsedWav, requestedChunkMs: number): number {
  const payloadBudget = alignBlock(MAX_PROVIDER_RAW_BYTES - WAV_HEADER_BYTES, wav.blockAlign);
  if (payloadBudget <= 0) {
    throw new Error("ASR chunk payload limit is too small for WAV chunks.");
  }
  const maxChunkMs = Math.floor((payloadBudget / wav.byteRate) * 1000);
  return Math.max(1, Math.min(requestedChunkMs, maxChunkMs));
}

function readAscii(view: DataView, offset: number, length: number): string {
  return String.fromCharCode(...Array.from({ length }, (_, index) => view.getUint8(offset + index)));
}

function writeAscii(view: DataView, offset: number, value: string): void {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index));
  }
}

function alignBlock(value: number, blockAlign: number): number {
  return Math.max(0, Math.floor(value / blockAlign) * blockAlign);
}

function baseName(name: string): string {
  return name.replace(/\.[^.]+$/, "").replace(/[^a-z0-9_.-]+/gi, "_") || "chunk";
}
