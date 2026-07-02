import type { ReactNode, RefObject } from "react";
import { useI18n } from "../i18n";
import { FullscreenTextEditor } from "./FullscreenTextEditor";

type ScriptFieldProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  optional?: boolean;
  required?: boolean;
  /** When true, a file-import button is shown next to the label; selecting a
   *  text/markdown file reads its content into `value` and calls onImportFormat
   *  so the caller can update its format selector. This replaces the old
   *  two-source (text vs file) model: importing a file IS editing the script. */
  importable?: boolean;
  onImportFormat?: (format: "plain" | "markdown" | "auto") => void;
  importDisabled?: boolean;
  ariaLabel?: string;
  /** Optional ref to the underlying textarea (for caret-based tag insertion). */
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
  /** Extra content rendered in the card header (e.g. a switch). */
  extraHeader?: ReactNode;
};

const PLAIN_SUFFIXES = [".txt"];
const MD_SUFFIXES = [".md", ".markdown"];

export function ScriptField({
  label,
  value,
  onChange,
  placeholder,
  rows = 6,
  optional,
  required,
  importable,
  onImportFormat,
  importDisabled,
  ariaLabel,
  textareaRef,
  extraHeader,
}: ScriptFieldProps) {
  const { t } = useI18n();

  function handleImport(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // Always reset so selecting the same file again re-triggers.
    event.target.value = "";
    if (!file) {
      return;
    }
    file
      .text()
      .then((content) => {
        onChange(content);
        onImportFormat?.(inferFormat(file.name));
      })
      .catch(() => {
        /* ignore read errors — leave existing value intact */
      });
  }

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">{label}</span>
        <div className="card-actions">
          {extraHeader}
          {importable ? (
            <label className={`btn btn-secondary import-btn${importDisabled ? " disabled" : ""}`}>
              <span>{t("tts.importScript")}</span>
              <input
                type="file"
                accept=".txt,.md,.markdown,text/plain,text/markdown"
                onChange={handleImport}
                disabled={importDisabled}
                aria-label={t("tts.importScriptAria")}
                hidden
              />
            </label>
          ) : null}
          {optional ? (
            <span className="char-count">{t("tts.optional")}</span>
          ) : (
            <span className="char-count">{t("common.chars", { count: value.length })}</span>
          )}
          <FullscreenTextEditor title={label} value={value} onApply={onChange} />
        </div>
      </div>
      <textarea
        className="script-input"
        ref={textareaRef}
        value={value}
        rows={rows}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        required={required}
        aria-label={ariaLabel ?? label}
      />
    </div>
  );
}

function inferFormat(name: string): "plain" | "markdown" | "auto" {
  const lower = name.toLowerCase();
  if (MD_SUFFIXES.some((suffix) => lower.endsWith(suffix))) return "markdown";
  if (PLAIN_SUFFIXES.some((suffix) => lower.endsWith(suffix))) return "plain";
  return "auto";
}
