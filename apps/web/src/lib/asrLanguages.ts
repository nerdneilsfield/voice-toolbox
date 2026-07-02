import type { Provider } from "../api";
import type { TranslationKey } from "../i18n/types";

export type AsrLanguageOption = {
  value: string;
  labelKey: TranslationKey;
};

export const BASIC_ASR_LANGUAGE_OPTIONS: readonly AsrLanguageOption[] = [
  { value: "auto", labelKey: "asr.languageOption.auto" },
  { value: "zh", labelKey: "asr.languageOption.zh" },
  { value: "en", labelKey: "asr.languageOption.en" },
];
export const QWEN3_ASR_LANGUAGE_OPTIONS: readonly AsrLanguageOption[] = [
  { value: "auto", labelKey: "asr.languageOption.auto" },
  { value: "zh", labelKey: "asr.languageOption.zh" },
  { value: "yue", labelKey: "asr.languageOption.yue" },
  { value: "en", labelKey: "asr.languageOption.en" },
  { value: "de", labelKey: "asr.languageOption.de" },
  { value: "es", labelKey: "asr.languageOption.es" },
  { value: "fr", labelKey: "asr.languageOption.fr" },
  { value: "it", labelKey: "asr.languageOption.it" },
  { value: "pt", labelKey: "asr.languageOption.pt" },
  { value: "ru", labelKey: "asr.languageOption.ru" },
  { value: "ko", labelKey: "asr.languageOption.ko" },
  { value: "ja", labelKey: "asr.languageOption.ja" },
];
export const FISH_ASR_LANGUAGE_OPTIONS = QWEN3_ASR_LANGUAGE_OPTIONS;

export function asrLanguageOptionsForProvider(provider: Provider | null | undefined): readonly AsrLanguageOption[] {
  if (provider?.type === "fish_audio") return FISH_ASR_LANGUAGE_OPTIONS;
  if (provider?.type === "mlx_audio") return QWEN3_ASR_LANGUAGE_OPTIONS;
  return BASIC_ASR_LANGUAGE_OPTIONS;
}
