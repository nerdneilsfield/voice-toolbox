import { en } from "./dictionaries";

export type Locale = "en" | "zh";
export type TranslationKey = keyof typeof en;
export type InterpolationValues = Record<string, string | number>;
