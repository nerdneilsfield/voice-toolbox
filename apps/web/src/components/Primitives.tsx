import type { ReactNode } from "react";
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
