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
  const wav = parseWav(buffer);
  const bytesPerMs = wav.byteRate / 1000 || 1;
  const chunkMs = Math.max(1000, targetSeconds * 1000);
  if (overlapMs >= chunkMs / 2) {
    throw new Error("ASR chunk overlap must be less than half of chunk duration.");
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
