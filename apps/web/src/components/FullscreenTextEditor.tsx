import { useEffect, useState, type KeyboardEvent } from "react";

type FullscreenTextEditorProps = {
  title: string;
  value: string;
  onApply(value: string): void;
  buttonLabel?: string;
};

export function FullscreenTextEditor({ title, value, onApply, buttonLabel = "Fullscreen" }: FullscreenTextEditorProps) {
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
      <button className="secondary-action" type="button" onClick={() => setOpen(true)}>
        {buttonLabel}
      </button>
      {open ? (
        <div className="modal-overlay" role="presentation">
          <section className="fullscreen-editor" role="dialog" aria-modal="true" aria-labelledby="fullscreen-title">
            <header className="fullscreen-editor__header">
              <h2 id="fullscreen-title">{title}</h2>
              <button className="secondary-action" type="button" onClick={() => setOpen(false)}>
                Cancel
              </button>
            </header>
            <textarea
              className="fullscreen-editor__textarea"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleEditorKeyDown}
              autoFocus
            />
            <footer className="fullscreen-editor__footer">
              <span>{draft.length} chars</span>
              <button className="primary-action compact-action" type="button" onClick={apply}>
                Apply
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}
