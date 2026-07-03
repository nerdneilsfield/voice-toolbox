import { afterEach, describe, expect, it, vi } from "vitest";
import { inspectWavFile, sliceWavFile } from "./audioChunks";

describe("browser audio chunk helpers", () => {
  it("decodes and slices WAV audio with overlap", async () => {
    const wav = makeWavFile("meeting.wav", {
      sampleRate: 1000,
      channels: 1,
      bitsPerSample: 16,
      frames: 2500,
    });

    const info = await inspectWavFile(wav);
    const { chunks, sourceDurationMs } = await sliceWavFile(wav, { targetSeconds: 1, overlapMs: 250 });

    expect(info.durationMs).toBe(2500);
    expect(sourceDurationMs).toBe(2500);
    expect(chunks).toHaveLength(4);
    expect(chunks.map((chunk) => chunk.offsetMs)).toEqual([0, 750, 1500, 2250]);
    expect(chunks[0].fileName).toBe("meeting.0.wav");
    expect(chunks[0].blob.type).toBe("audio/wav");
  });

  it("caps browser chunk duration so each WAV upload fits provider payload limit", async () => {
    const wav = makeWavFile("studio.wav", {
      sampleRate: 48000,
      channels: 8,
      bitsPerSample: 32,
      frames: 576000,
    });

    const { chunks } = await sliceWavFile(wav, { targetSeconds: 10, overlapMs: 0 });

    expect(chunks.length).toBeGreaterThan(1);
    await Promise.all(
      chunks.map(async (chunk) => {
        expect(chunk.blob.size).toBeLessThanOrEqual(Math.floor((10 * 1024 * 1024) / 4) * 3);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("decodes browser-supported non-WAV input and slices it as WAV chunks", async () => {
    vi.stubGlobal(
      "AudioContext",
      class {
        async decodeAudioData() {
          return {
            duration: 2.5,
            length: 2500,
            numberOfChannels: 1,
            sampleRate: 1000,
            getChannelData: () => new Float32Array(2500).fill(0.25),
          };
        }

        async close() {
          return undefined;
        }
      },
    );
    const file = new File(["not wav"], "meeting.mp3", { type: "audio/mpeg" });

    const { chunks, sourceDurationMs } = await sliceWavFile(file, { targetSeconds: 1, overlapMs: 250 });

    expect(sourceDurationMs).toBe(2500);
    expect(chunks).toHaveLength(4);
    expect(chunks.map((chunk) => chunk.offsetMs)).toEqual([0, 750, 1500, 2250]);
    expect(chunks[0].fileName).toBe("meeting.0.wav");
    expect(chunks[0].blob.type).toBe("audio/wav");
  });

  it("throws for non-PCM WAV input so callers can fallback to backend upload", async () => {
    const wav = makeWavFile("float.wav", {
      sampleRate: 1000,
      channels: 1,
      bitsPerSample: 32,
      frames: 100,
      audioFormat: 3,
    });

    await expect(sliceWavFile(wav, { targetSeconds: 30, overlapMs: 1000 })).rejects.toThrow(
      "Browser chunking currently supports PCM WAV input only.",
    );
  });
});

function makeWavFile(
  name: string,
  {
    sampleRate,
    channels,
    bitsPerSample,
    frames,
    audioFormat = 1,
  }: {
    sampleRate: number;
    channels: number;
    bitsPerSample: number;
    frames: number;
    audioFormat?: number;
  },
) {
  const bytesPerSample = bitsPerSample / 8;
  const blockAlign = channels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataSize = frames * blockAlign;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, audioFormat, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, dataSize, true);
  return new File([buffer], name, { type: "audio/wav" });
}

function writeAscii(view: DataView, offset: number, value: string) {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index));
  }
}
