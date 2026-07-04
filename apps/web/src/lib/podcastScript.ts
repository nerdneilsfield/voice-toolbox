import type { PodcastScriptFormat } from "../api";

export type PodcastPreviewSpeaker = { id: string; name: string };
export type PodcastPreviewSegment = {
  speakerId: string;
  speakerName: string;
  text: string;
  pauseAfterMs: number;
  line: number;
};
export type PodcastPreviewError = { line?: number; message: string };
export type PodcastPreview = {
  speakers: PodcastPreviewSpeaker[];
  segments: PodcastPreviewSegment[];
  errors: PodcastPreviewError[];
};

const speakerLinePattern = /^\s*([^:\n]{1,80}):\s*(.*?)\s*$/;
const headingPattern = /^\s{0,3}#{1,3}\s+(.+?)\s*$/m;
const lineHeadingPattern = /^\s{0,3}#{1,3}\s+(.+?)\s*$/;
const pausePattern = /\[pause:(\d+)\]\s*$/;
const standalonePausePattern = /^\s*\[pause:(\d+)\]\s*$/;

export function parsePodcastScriptPreview(
  script: string,
  format: PodcastScriptFormat,
  defaultPauseMs: number,
): PodcastPreview {
  const resolved = resolveFormat(script, format);
  if (resolved === "markdown") return parseMarkdownPreview(script, defaultPauseMs);
  if (resolved === "json") return parseJsonPreview(script, defaultPauseMs);
  if (resolved === "yaml") return parseYamlPreview(script, defaultPauseMs);
  return parseSpeakerLinePreview(script, defaultPauseMs);
}

function resolveFormat(script: string, format: PodcastScriptFormat): Exclude<PodcastScriptFormat, "auto"> {
  if (format !== "auto") return format;
  const trimmed = script.trimStart();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) return "json";
  if (headingPattern.test(script)) return "markdown";
  if (/^\s*lines\s*:/m.test(script)) return "yaml";
  return "speaker_colon";
}

function parseSpeakerLinePreview(script: string, defaultPauseMs: number): PodcastPreview {
  const speakers = new Map<string, PodcastPreviewSpeaker>();
  const usedSpeakerIds = new Set<string>();
  const segments: PodcastPreviewSegment[] = [];
  const errors: PodcastPreviewError[] = [];
  for (const [offset, line] of script.split(/\r?\n/).entries()) {
    const lineNo = offset + 1;
    if (!line.trim()) continue;
    const standalonePause = standalonePausePattern.exec(line);
    if (standalonePause) {
      if (segments.length === 0) {
        errors.push({ line: lineNo, message: "Pause directive requires a preceding segment" });
      } else {
        const previous = segments[segments.length - 1];
        segments[segments.length - 1] = { ...previous, pauseAfterMs: Number(standalonePause[1]) };
      }
      continue;
    }
    if (line.trim().startsWith("[pause:")) {
      errors.push({ line: lineNo, message: "Invalid pause directive" });
      continue;
    }
    const match = speakerLinePattern.exec(line);
    if (!match) {
      errors.push({ line: lineNo, message: "Expected Speaker: text" });
      continue;
    }
    addPreviewSegment(speakers, usedSpeakerIds, segments, errors, match[1].trim(), match[2], lineNo, defaultPauseMs);
  }
  return { speakers: Array.from(speakers.values()), segments, errors };
}

function parseMarkdownPreview(script: string, defaultPauseMs: number): PodcastPreview {
  const speakers = new Map<string, PodcastPreviewSpeaker>();
  const usedSpeakerIds = new Set<string>();
  const segments: PodcastPreviewSegment[] = [];
  const errors: PodcastPreviewError[] = [];
  let currentSpeaker = "";
  let paragraph: string[] = [];
  let paragraphLine = 1;
  const flush = () => {
    if (!currentSpeaker || paragraph.length === 0) {
      paragraph = [];
      return;
    }
    addPreviewSegment(
      speakers,
      usedSpeakerIds,
      segments,
      errors,
      currentSpeaker,
      paragraph.join(" "),
      paragraphLine,
      defaultPauseMs,
    );
    paragraph = [];
  };
  for (const [offset, line] of script.split(/\r?\n/).entries()) {
    const lineNo = offset + 1;
    const heading = lineHeadingPattern.exec(line);
    if (heading) {
      flush();
      currentSpeaker = heading[1].trim();
      continue;
    }
    if (!line.trim()) {
      flush();
      continue;
    }
    if (!currentSpeaker) {
      errors.push({ line: lineNo, message: "Expected speaker heading" });
      continue;
    }
    if (paragraph.length === 0) paragraphLine = lineNo;
    paragraph.push(line.trim());
  }
  flush();
  return { speakers: Array.from(speakers.values()), segments, errors };
}

function parseJsonPreview(script: string, defaultPauseMs: number): PodcastPreview {
  const speakers = new Map<string, PodcastPreviewSpeaker>();
  const usedSpeakerIds = new Set<string>();
  const segments: PodcastPreviewSegment[] = [];
  const errors: PodcastPreviewError[] = [];
  try {
    const payload = JSON.parse(script) as {
      lines?: Array<{ speaker?: unknown; text?: unknown; pause_after_ms?: unknown }>;
    };
    if (!Array.isArray(payload.lines)) {
      return { speakers: [], segments: [], errors: [{ message: "JSON requires lines list" }] };
    }
    for (const [index, line] of payload.lines.entries()) {
      if (typeof line.speaker !== "string" || typeof line.text !== "string") {
        errors.push({ line: index + 1, message: "Line requires speaker and text" });
        continue;
      }
      const pause = parseStructuredPause(line.pause_after_ms, defaultPauseMs);
      if (pause === null) {
        errors.push({ line: index + 1, message: "pause_after_ms must be a non-negative integer" });
        continue;
      }
      addPreviewSegment(speakers, usedSpeakerIds, segments, errors, line.speaker, line.text, index + 1, pause);
    }
  } catch {
    errors.push({ message: "Invalid JSON" });
  }
  return { speakers: Array.from(speakers.values()), segments, errors };
}

function parseYamlPreview(script: string, defaultPauseMs: number): PodcastPreview {
  const speakers = new Map<string, PodcastPreviewSpeaker>();
  const usedSpeakerIds = new Set<string>();
  const segments: PodcastPreviewSegment[] = [];
  const errors: PodcastPreviewError[] = [];
  let current: { speaker?: string; text?: string; pause?: number; line: number } | null = null;
  const flush = () => {
    if (!current) return;
    if (!current.speaker || !current.text) {
      errors.push({ line: current.line, message: "Line requires speaker and text" });
    } else {
      addPreviewSegment(
        speakers,
        usedSpeakerIds,
        segments,
        errors,
        current.speaker,
        current.text,
        current.line,
        current.pause ?? defaultPauseMs,
      );
    }
    current = null;
  };
  for (const [offset, rawLine] of script.split(/\r?\n/).entries()) {
    const lineNo = offset + 1;
    const line = rawLine.trim();
    if (!line || line === "lines:") continue;
    if (line.startsWith("- ")) {
      flush();
      current = { line: lineNo };
      assignYamlField(current, line.slice(1).trim(), errors);
      continue;
    }
    if (!current) continue;
    assignYamlField(current, line, errors);
  }
  flush();
  return { speakers: Array.from(speakers.values()), segments, errors };
}

function assignYamlField(
  current: { speaker?: string; text?: string; pause?: number; line: number },
  field: string,
  errors: PodcastPreviewError[],
): void {
  const match = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(field);
  if (!match) return;
  const value = stripYamlQuotes(match[2].trim());
  if (match[1] === "speaker") current.speaker = value;
  if (match[1] === "text") current.text = value;
  if (match[1] === "pause_after_ms") {
    if (!/^\d+$/.test(value)) {
      errors.push({ line: current.line, message: "pause_after_ms must be a non-negative integer" });
      return;
    }
    current.pause = Number(value);
  }
}

function addPreviewSegment(
  speakers: Map<string, PodcastPreviewSpeaker>,
  usedSpeakerIds: Set<string>,
  segments: PodcastPreviewSegment[],
  errors: PodcastPreviewError[],
  name: string,
  rawText: string,
  line: number,
  defaultPauseMs: number,
): void {
  const parsedText = parsePause(rawText, defaultPauseMs);
  if (parsedText.error) {
    errors.push({ line, message: parsedText.error });
    return;
  }
  if (!parsedText.text) return;
  const trimmedName = name.trim();
  if (!speakers.has(trimmedName)) {
    speakers.set(trimmedName, { id: slugSpeaker(trimmedName, usedSpeakerIds), name: trimmedName });
  }
  const speaker = speakers.get(trimmedName)!;
  segments.push({
    speakerId: speaker.id,
    speakerName: speaker.name,
    text: parsedText.text,
    pauseAfterMs: parsedText.pauseAfterMs,
    line,
  });
}

function parsePause(raw: string, defaultPauseMs: number): { text: string; pauseAfterMs: number; error?: string } {
  if (raw.includes("[pause:") && !pausePattern.test(raw)) {
    return { text: raw.trim(), pauseAfterMs: defaultPauseMs, error: "Invalid pause directive" };
  }
  const match = pausePattern.exec(raw);
  if (!match) return { text: raw.trim(), pauseAfterMs: defaultPauseMs };
  return { text: raw.slice(0, match.index).trim(), pauseAfterMs: Number(match[1]) };
}

function parseStructuredPause(value: unknown, defaultPauseMs: number): number | null {
  if (value === undefined || value === null) return defaultPauseMs;
  if (Number.isInteger(value) && Number(value) >= 0) return Number(value);
  return null;
}

function slugSpeaker(name: string, existing: Set<string>): string {
  const base = name
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  const fallback = base || "speaker";
  let candidate = fallback;
  let index = 2;
  while (existing.has(candidate)) {
    candidate = `${fallback}-${index}`;
    index += 1;
  }
  existing.add(candidate);
  return candidate;
}

function stripYamlQuotes(value: string): string {
  const singleQuoted = value.startsWith("'") && value.endsWith("'");
  const doubleQuoted = value.startsWith('"') && value.endsWith('"');
  return singleQuoted || doubleQuoted ? value.slice(1, -1) : value;
}
