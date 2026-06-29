import { useEffect, useState, type KeyboardEvent } from "react";
import { useI18n } from "../i18n";

type FullscreenTextEditorProps = {
  title: string;
  value: string;
  onApply(value: string): void;
};

export function FullscreenTextEditor({ title, value, onApply }: FullscreenTextEditorProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    if (open) {
      setDraft(value);
    }
  }, [open, value]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  function apply() {
    onApply(draft);
    setOpen(false);
  }

  function handleEditorKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      apply();
    }
  }

  return (
    <>
      <button
        className="expand-link"
        type="button"
        onClick={() => setOpen(true)}
        title={t("fullscreen.expand")}
        aria-label={t("fullscreen.expandAria")}
      >
        ↗
      </button>
      {open ? (
        <div className="modal-overlay" role="presentation">
          <section className="fullscreen-editor" role="dialog" aria-modal="true" aria-labelledby="fullscreen-title">
            <header className="fullscreen-editor__header">
              <h2 id="fullscreen-title">{title}</h2>
              <button className="btn btn-secondary" type="button" onClick={() => setOpen(false)}>
                {t("fullscreen.cancel")}
              </button>
            </header>
            <textarea
              className="fullscreen-editor__textarea script-input"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleEditorKeyDown}
              autoFocus
            />
            <footer className="fullscreen-editor__footer">
              <span>{t("common.chars", { count: draft.length })}</span>
              <button className="btn btn-primary" type="button" onClick={apply}>
                {t("fullscreen.apply")}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}
