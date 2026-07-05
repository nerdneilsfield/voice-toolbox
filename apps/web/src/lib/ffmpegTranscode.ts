import ffmpegCoreURL from "@ffmpeg/core?url";
import ffmpegCoreWasmURL from "@ffmpeg/core/wasm?url";

let ffmpegPromise: Promise<unknown> | null = null;
let transcodeQueue: Promise<void> = Promise.resolve();

type FfmpegLike = {
  load: (options?: Record<string, unknown>) => Promise<void>;
  writeFile: (path: string, data: Uint8Array) => Promise<void>;
  exec: (args: string[]) => Promise<number>;
  readFile: (path: string) => Promise<Uint8Array | string>;
  deleteFile?: (path: string) => Promise<void>;
};

declare global {
  var __VOICE_TOOLBOX_FFMPEG_TRANSCODE__: ((file: File) => Promise<ArrayBuffer>) | undefined;
}

export async function transcodeAudioToWavWithFfmpeg(file: File): Promise<ArrayBuffer> {
  if (globalThis.__VOICE_TOOLBOX_FFMPEG_TRANSCODE__) {
    return globalThis.__VOICE_TOOLBOX_FFMPEG_TRANSCODE__(file);
  }

  const ffmpeg = (await loadFfmpeg()) as FfmpegLike;
  return enqueueTranscode(() => runFfmpegTranscode(ffmpeg, file));
}

async function runFfmpegTranscode(ffmpeg: FfmpegLike, file: File): Promise<ArrayBuffer> {
  const operationId = uniqueOperationId();
  const inputName = `input-${operationId}.${inputSuffix(file.name)}`;
  const outputName = `output-${operationId}.wav`;
  const inputBytes = new Uint8Array(await file.arrayBuffer());
  await ffmpeg.writeFile(inputName, inputBytes);
  try {
    const exitCode = await ffmpeg.exec([
      "-i",
      inputName,
      "-ac",
      "1",
      "-ar",
      "24000",
      "-sample_fmt",
      "s16",
      "-f",
      "wav",
      outputName,
    ]);
    if (exitCode !== 0) {
      throw new Error("ffmpeg wasm audio transcode failed");
    }
    const data = await ffmpeg.readFile(outputName);
    if (typeof data === "string") {
      throw new Error("ffmpeg wasm returned text output");
    }
    return new Uint8Array(data).slice().buffer;
  } finally {
    await Promise.all([
      ffmpeg.deleteFile?.(inputName).catch(() => undefined),
      ffmpeg.deleteFile?.(outputName).catch(() => undefined),
    ]);
  }
}

function enqueueTranscode<T>(operation: () => Promise<T>): Promise<T> {
  const runAfterPrior = transcodeQueue.then(operation, operation);
  transcodeQueue = runAfterPrior.then(
    () => undefined,
    () => undefined,
  );
  return runAfterPrior;
}

async function loadFfmpeg(): Promise<unknown> {
  if (!ffmpegPromise) {
    ffmpegPromise = createAndLoadFfmpeg().catch((error: unknown) => {
      ffmpegPromise = null;
      throw error;
    });
  }
  return ffmpegPromise;
}

async function createAndLoadFfmpeg(): Promise<unknown> {
  const [{ FFmpeg }, { toBlobURL }] = await Promise.all([import("@ffmpeg/ffmpeg"), import("@ffmpeg/util")]);
  const ffmpeg = new FFmpeg();
  await ffmpeg.load({
    coreURL: await toBlobURL(ffmpegCoreURL, "text/javascript"),
    wasmURL: await toBlobURL(ffmpegCoreWasmURL, "application/wasm"),
  });
  return ffmpeg;
}

function inputSuffix(name: string): string {
  const suffix = name
    .split(".")
    .pop()
    ?.toLowerCase()
    .replace(/[^a-z0-9]/g, "");
  return suffix || "audio";
}

function uniqueOperationId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
