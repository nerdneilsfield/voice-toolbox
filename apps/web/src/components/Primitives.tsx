import type { ChangeEvent, ReactNode } from "react";
import { useI18n } from "../i18n";
import styles from "./Primitives.module.css";

export function Notice({ variant = "info", children }: { variant?: "info" | "error"; children: ReactNode }) {
  return <div className={`${styles.notice} ${variant === "error" ? styles.error : ""}`}>{children}</div>;
}

export function EmptyState({ title }: { title: string }) {
  return (
    <div className={styles.empty}>
      <div className={styles.waveform} aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
        <span />
      </div>
      <p>{title}</p>
    </div>
  );
}

export function LoadingState({ lines }: { lines: number }) {
  const { t } = useI18n();
  return (
    <div className={styles.loading} aria-label={t("common.loading")}>
      {Array.from({ length: lines }).map((_, index) => (
        <span key={index} />
      ))}
    </div>
  );
}

type FilePickerProps = {
  accept: string;
  buttonLabel: string;
  emptyLabel: string;
  selectedName?: string | null;
  required?: boolean;
  onChange: (file: File | null) => void;
};

export function FilePicker({ accept, buttonLabel, emptyLabel, selectedName, required, onChange }: FilePickerProps) {
  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    onChange(event.target.files?.[0] ?? null);
  }

  return (
    <span className="file-picker">
      <input className="sr-only" type="file" accept={accept} onChange={handleChange} required={required} />
      <span className="file-picker-button">{buttonLabel}</span>
      <span className="file-picker-name">{selectedName || emptyLabel}</span>
    </span>
  );
}
