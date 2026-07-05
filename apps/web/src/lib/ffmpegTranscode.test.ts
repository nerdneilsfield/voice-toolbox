import { beforeEach, describe, expect, it, vi } from "vitest";

describe("ffmpeg wasm transcode", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
  });

  it("retries loading ffmpeg after a transient load failure", async () => {
    let loadCalls = 0;
    vi.doMock("@ffmpeg/ffmpeg", () => ({
      FFmpeg: class {
        async load() {
          loadCalls += 1;
          if (loadCalls === 1) {
            throw new Error("transient load failure");
          }
        }

        async writeFile() {
          return undefined;
        }

        async exec() {
          return 0;
        }

        async readFile() {
          return new Uint8Array([1, 2, 3]);
        }

        async deleteFile() {
          return undefined;
        }
      },
    }));
    vi.doMock("@ffmpeg/util", () => ({ toBlobURL: (url: string) => Promise.resolve(url) }));
    const { transcodeAudioToWavWithFfmpeg } = await import("./ffmpegTranscode");
    const file = new File(["audio"], "speech.flac", { type: "audio/flac" });

    await expect(transcodeAudioToWavWithFfmpeg(file)).rejects.toThrow("transient load failure");
    await expect(transcodeAudioToWavWithFfmpeg(file)).resolves.toBeInstanceOf(ArrayBuffer);
    expect(loadCalls).toBe(2);
  });

  it("serializes transcodes and uses unique workspace file names", async () => {
    let releaseFirstExec: (() => void) | null = null;
    let activeExecs = 0;
    let maxActiveExecs = 0;
    const execInputs: string[] = [];
    const execOutputs: string[] = [];
    const writeNames: string[] = [];

    vi.doMock("@ffmpeg/ffmpeg", () => ({
      FFmpeg: class {
        async load() {
          return undefined;
        }

        async writeFile(path: string) {
          writeNames.push(path);
        }

        async exec(args: string[]) {
          activeExecs += 1;
          maxActiveExecs = Math.max(maxActiveExecs, activeExecs);
          execInputs.push(args[1]);
          execOutputs.push(args.at(-1) ?? "");
          if (!releaseFirstExec) {
            await new Promise<void>((resolve) => {
              releaseFirstExec = resolve;
            });
          }
          activeExecs -= 1;
          return 0;
        }

        async readFile() {
          return new Uint8Array([1, 2, 3]);
        }

        async deleteFile() {
          return undefined;
        }
      },
    }));
    vi.doMock("@ffmpeg/util", () => ({ toBlobURL: (url: string) => Promise.resolve(url) }));
    const { transcodeAudioToWavWithFfmpeg } = await import("./ffmpegTranscode");

    const first = transcodeAudioToWavWithFfmpeg(new File(["one"], "one.flac"));
    const second = transcodeAudioToWavWithFfmpeg(new File(["two"], "two.flac"));
    await vi.waitFor(() => expect(releaseFirstExec).toBeTypeOf("function"));
    await Promise.resolve();
    expect(maxActiveExecs).toBe(1);
    (releaseFirstExec as (() => void) | null)?.();
    await Promise.all([first, second]);

    expect(new Set(writeNames).size).toBe(2);
    expect(new Set(execInputs).size).toBe(2);
    expect(new Set(execOutputs).size).toBe(2);
  });
});
