import { createContext, useEffect, useState, type ReactNode } from "react";

export type ThemePreference = "light" | "dark" | "system";
export type EffectiveTheme = "light" | "dark";

const STORAGE_KEY = "voice-toolbox-theme";

const ThemeContext = createContext<{
  theme: ThemePreference;
  effectiveTheme: EffectiveTheme;
  setTheme: (theme: ThemePreference) => void;
  cycleTheme: () => void;
} | null>(null);

function resolveEffective(theme: ThemePreference): EffectiveTheme {
  if (theme !== "system") return theme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function normalizeSavedTheme(value: string | null): ThemePreference {
  if (value === "light" || value === "dark" || value === "system") return value;
  if (value === "auto") return "system";
  return "system";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemePreference>(() => {
    const saved = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    return normalizeSavedTheme(saved);
  });
  const [effectiveTheme, setEffectiveTheme] = useState<EffectiveTheme>(() => resolveEffective(theme));

  useEffect(() => {
    setEffectiveTheme(resolveEffective(theme));
  }, [theme]);

  useEffect(() => {
    document.documentElement.dataset.theme = effectiveTheme;
  }, [effectiveTheme]);

  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = (event: MediaQueryListEvent) => setEffectiveTheme(event.matches ? "dark" : "light");
    mq.addEventListener("change", listener);
    return () => mq.removeEventListener("change", listener);
  }, [theme]);

  const setTheme = (next: ThemePreference) => {
    localStorage.setItem(STORAGE_KEY, next);
    setThemeState(next);
  };

  const cycleTheme = () => {
    const order: ThemePreference[] = ["light", "dark", "system"];
    setTheme(order[(order.indexOf(theme) + 1) % order.length]);
  };

  return (
    <ThemeContext.Provider value={{ theme, effectiveTheme, setTheme, cycleTheme }}>{children}</ThemeContext.Provider>
  );
}

export { ThemeContext };
