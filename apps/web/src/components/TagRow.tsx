import { useRef, useState } from "react";
import { useI18n } from "../i18n";

const INLINE_TAGS = ["(唱歌)", "(笑)", "(叹气)", "(停顿)", "[breath]", "[laughter]"];

type TagRowProps = {
  /** Insert `tag` into the script at the textarea's current caret position. */
  onInsert: (tag: string) => void;
};

/**
 * Inline-emotion tag chips + a custom-tag input. `onInsert` receives the tag
 * to splice into the bound textarea; this component is purely presentational
 * aside from its own custom-tag draft state.
 */
export function TagRow({ onInsert }: TagRowProps) {
  const { t } = useI18n();
  const [customTag, setCustomTag] = useState("");
  const draftRef = useRef("");

  function submitCustom() {
    const trimmed = customTag.trim();
    if (!trimmed) {
      return;
    }
    const normalized = /^[([]/.test(trimmed) ? trimmed : `(${trimmed})`;
    onInsert(normalized);
    setCustomTag("");
    draftRef.current = "";
  }

  return (
    <div className="tag-row">
      {INLINE_TAGS.map((tag) => (
        <button key={tag} className="chip" type="button" onClick={() => onInsert(tag)}>
          {tag}
        </button>
      ))}
      <input
        type="text"
        className="tag-input"
        value={customTag}
        onChange={(event) => {
          setCustomTag(event.target.value);
          draftRef.current = event.target.value;
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            submitCustom();
          }
        }}
        placeholder={t("tts.customTagPlaceholder")}
      />
    </div>
  );
}
