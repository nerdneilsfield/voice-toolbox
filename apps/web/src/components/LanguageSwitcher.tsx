import { useI18n } from "../i18n";

export function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n();
  return (
    <div className="language-switcher" role="group" aria-label={t("lang.en") + " / " + t("lang.zh")}>
      {(["en", "zh"] as const).map((code) => (
        <button
          key={code}
          type="button"
          className={["btn", "btn-ghost", locale === code ? "active" : ""].filter(Boolean).join(" ")}
          onClick={() => setLocale(code)}
          aria-pressed={locale === code}
        >
          {t(`lang.${code}`)}
        </button>
      ))}
    </div>
  );
}
