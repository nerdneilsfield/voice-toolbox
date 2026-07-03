import { useCallback, useRef, useState } from "react";
import type { ChunkingMode, OperationResponse } from "../api";
import {
  createAsrChunkSession,
  deleteAsrChunkSession,
  finishAsrChunkSession,
  transcribe,
  uploadAsrChunk,
} from "../api";
import { sliceWavFile } from "../lib/audioChunks";
import { useI18n } from "../i18n";

export type AsrChunkPhase = "idle" | "preparing" | "uploading" | "finishing" | "canceling";

export type AsrChunkProgress = {
  phase: AsrChunkPhase;
  message: string;
  current?: number;
  total?: number;
};

export type AsrChunkConfig = {
  providerId: string;
  model: string | null;
  language: string;
  chunkSeconds: number;
  overlapMs: number;
  chunkingMode: ChunkingMode;
  uploadStrategy: "auto" | "browser" | "backend";
  transcriptTimestamps: boolean;
  transcriptSpeakers: boolean;
};

const BASE64_LIMIT_BYTES = 10 * 1024 * 1024;

function shouldUseBrowserChunks(file: File, mode: ChunkingMode, strategy: "auto" | "browser" | "backend"): boolean {
  if (mode === "off" || strategy === "backend") {
    return false;
  }
  const isWav = file.type === "audio/wav" || file.type === "audio/x-wav" || /\.wav$/i.test(file.name);
  return strategy === "browser" || mode === "force" || isWav || file.size > BASE64_LIMIT_BYTES;
}

/**
 * Encapsulates the multi-step browser chunk upload (create -> upload loop ->
 * finish) with cancel/abort and automatic backend fallback. Returns a stable
 * `run` plus live progress/session state so the component layer stays declarative.
 */
export function useAsrChunkUpload(config: AsrChunkConfig) {
  const { t } = useI18n();
  const [progress, setProgress] = useState<AsrChunkProgress | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const cancelRequestedRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(
    async (file: File, providerOptions: Record<string, unknown>): Promise<OperationResponse> => {
      cancelRequestedRef.current = false;

      if (!shouldUseBrowserChunks(file, config.chunkingMode, config.uploadStrategy)) {
        setProgress(null);
        return transcribe(buildBackendForm(file, config, providerOptions));
      }

      let session: string | null = null;
      const abort = new AbortController();
      abortRef.current = abort;
      try {
        setProgress({ phase: "preparing", message: t("asr.chunkPreparing") });
        const { chunks, sourceDurationMs } = await sliceWavFile(file, {
          targetSeconds: config.chunkSeconds,
          overlapMs: config.overlapMs,
        });
        throwIfCanceled(cancelRequestedRef);
        const created = await createAsrChunkSession({
          providerId: config.providerId,
          model: config.model,
          language: config.language,
          sourceDurationMs,
          totalChunks: chunks.length,
          sourceFileName: file.name,
          transcriptTimestamps: config.transcriptTimestamps,
          transcriptSpeakers: config.transcriptSpeakers,
          providerOptions,
          signal: abort.signal,
        });
        session = created.session_id;
        setSessionId(session);

        for (let index = 0; index < chunks.length; index += 1) {
          throwIfCanceled(cancelRequestedRef);
          const chunk = chunks[index];
          setProgress({
            phase: "uploading",
            message: t("asr.chunkUploading", { current: index + 1, total: chunks.length }),
            current: index + 1,
            total: chunks.length,
          });
          await uploadAsrChunk({
            sessionId: session,
            file: chunk.blob,
            fileName: chunk.fileName,
            chunkIndex: index,
            offsetMs: chunk.offsetMs,
            durationMs: chunk.durationMs,
            signal: abort.signal,
          });
        }
        throwIfCanceled(cancelRequestedRef);
        setProgress({ phase: "finishing", message: t("asr.chunkFinishing") });
        return await finishAsrChunkSession({
          sessionId: session,
          providerId: config.providerId,
          model: config.model,
          language: config.language,
          transcriptTimestamps: config.transcriptTimestamps,
          transcriptSpeakers: config.transcriptSpeakers,
          providerOptions,
          signal: abort.signal,
        });
      } catch (err) {
        if (session) {
          await safeDelete(session);
        }
        setSessionId(null);
        if (cancelRequestedRef.current) {
          throw new Error(t("asr.chunkUploadCanceled"), { cause: err });
        }
        // Browser path failed (non-cancel): fall back to a single backend upload.
        setProgress({
          phase: "uploading",
          message: t("asr.browserChunkFallback", {
            message: err instanceof Error ? err.message : t("errors.asrRequestFailed"),
          }),
        });
        return transcribe(buildBackendForm(file, config, providerOptions), abort.signal);
      } finally {
        if (abortRef.current === abort) {
          abortRef.current = null;
        }
        setSessionId(null);
      }
    },
    [config, t],
  );

  const cancel = useCallback(() => {
    cancelRequestedRef.current = true;
    abortRef.current?.abort();
    setProgress({ phase: "canceling", message: t("asr.chunkCanceling") });
    if (sessionId) {
      void safeDelete(sessionId);
    }
  }, [sessionId, t]);

  return { run, cancel, progress, sessionId, active: sessionId !== null };
}

function throwIfCanceled(ref: React.RefObject<boolean>) {
  if (ref.current) {
    throw new Error("canceled");
  }
}

async function safeDelete(sessionId: string) {
  try {
    await deleteAsrChunkSession(sessionId);
  } catch {
    /* session may already be gone */
  }
}

function buildBackendForm(file: File, config: AsrChunkConfig, providerOptions: Record<string, unknown>): FormData {
  const body = new FormData();
  body.set("provider_id", config.providerId);
  body.set("language", config.language);
  body.set("file", file);
  body.set("chunking_mode", config.chunkingMode);
  body.set("chunk_seconds", String(config.chunkSeconds));
  body.set("chunk_overlap_ms", String(config.overlapMs));
  body.set("transcript_timestamps", String(config.transcriptTimestamps));
  body.set("transcript_speakers", String(config.transcriptSpeakers));
  if (config.model) {
    body.set("model", config.model);
  }
  if (Object.keys(providerOptions).length > 0) {
    body.set("provider_options", JSON.stringify(providerOptions));
  }
  return body;
}
