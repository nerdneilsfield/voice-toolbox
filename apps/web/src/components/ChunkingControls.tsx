import type { ChunkingMode } from "../api";
import { useI18n } from "../i18n";

type ChunkingControlsProps = {
  mode: ChunkingMode;
  setMode: (value: ChunkingMode) => void;
  primaryLabel: string;
  primaryValue: number;
  setPrimaryValue: (value: number) => void;
  primaryMin?: number;
  secondaryLabel: string;
  secondaryValue: number;
  setSecondaryValue: (value: number) => void;
  secondaryMin?: number;
};

export function ChunkingControls({
  mode,
  setMode,
  primaryLabel,
  primaryValue,
  setPrimaryValue,
  primaryMin = 1,
  secondaryLabel,
  secondaryValue,
  setSecondaryValue,
  secondaryMin = 0,
}: ChunkingControlsProps) {
  const { t } = useI18n();
  return (
    <div className="chunking-controls">
      <label className="field">
        <span className="field-title">{t("chunking.mode")}</span>
        <select value={mode} onChange={(event) => setMode(event.target.value as ChunkingMode)}>
          <option value="off">{t("chunking.off")}</option>
          <option value="auto">{t("chunking.auto")}</option>
          <option value="force">{t("chunking.force")}</option>
        </select>
      </label>
      <label className="field">
        <span className="field-title">{primaryLabel}</span>
        <input
          type="number"
          min={primaryMin}
          value={primaryValue}
          onChange={(event) => setPrimaryValue(Number(event.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-title">{secondaryLabel}</span>
        <input
          type="number"
          min={secondaryMin}
          value={secondaryValue}
          onChange={(event) => setSecondaryValue(Number(event.target.value))}
        />
      </label>
    </div>
  );
}
