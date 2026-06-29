import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";

const ICONS: Record<"light" | "dark" | "auto", string> = {
  light: "☀️",
  dark: "🌙",
  auto: "🌓",
};

export function ThemeToggle() {
  const { theme, cycleTheme } = useTheme();
  const { t } = useI18n();
  return (
    <button
      type="button"
      className="btn btn-ghost theme-toggle"
      onClick={cycleTheme}
      aria-label={`Theme: ${t(`theme.${theme}`)}`}
    >
      <span aria-hidden="true">{ICONS[theme]}</span>
      <span className="theme-toggle-label">{t(`theme.${theme}`)}</span>
    </button>
  );
}
