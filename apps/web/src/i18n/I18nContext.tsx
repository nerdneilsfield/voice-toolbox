import { createContext, useCallback, useEffect, useState, type ReactNode } from "react";
import { en, zh } from "./dictionaries";
import type { InterpolationValues, Locale, TranslationKey } from "./types";

const STORAGE_KEY = "voice-toolbox-locale";

const dictionaries = { en, zh };

const I18nContext = createContext<{
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: TranslationKey, values?: InterpolationValues) => string;
  locales: readonly Locale[];
} | null>(null);

function translate(locale: Locale, key: TranslationKey, values?: InterpolationValues): string {
  const template = dictionaries[locale][key] ?? dictionaries.en[key] ?? key;
  if (!values) return template;
  return template.replace(/\{(\w+)\}/g, (_match, name) => String(values[name] ?? ""));
}

function detectDefaultLocale(): Locale {
  if (typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("zh")) {
    return "zh";
  }
  return "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => {
    const saved = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    if (saved === "en" || saved === "zh") return saved;
    return detectDefaultLocale();
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, locale);
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
  }, [locale]);

  const setLocale = useCallback((next: Locale) => setLocaleState(next), []);
  const t = useCallback(
    (key: TranslationKey, values?: InterpolationValues) => translate(locale, key, values),
    [locale],
  );

  return (
    <I18nContext.Provider value={{ locale, setLocale, t, locales: ["en", "zh"] }}>{children}</I18nContext.Provider>
  );
}

export { I18nContext };
