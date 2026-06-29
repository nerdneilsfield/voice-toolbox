# I18n & Theme Switching Design

## Goal

Add two user-facing preferences to the Voice Toolbox web UI:

1. **Language switching** between English (`en`) and Simplified Chinese (`zh`).
2. **Theme switching** among Light / Dark / System, where System follows the OS preference.

Both preferences persist in `localStorage` and apply immediately without a page reload.

## Architecture

### 1. Theme system

- A single `ThemeContext` exposes the stored preference (`light | dark | system`) and the resolved effective theme (`light | dark`).
- The resolved theme is written to `document.documentElement.dataset.theme`.
- CSS variables are kept in `:root` for the light theme. A new `html[data-theme="dark"]` block overrides the variables for dark mode.
- Hard-coded semantic colors in CSS (success/warning/danger backgrounds, spinner colors, focus rings) are mapped to CSS variables so dark mode can override them cleanly.
- A `ThemeToggle` component in the topbar lets the user cycle through Light → Dark → System → Light.

### 2. I18n system

- A custom `I18nContext` avoids adding a heavy dependency.
- Dictionaries live in `apps/web/src/i18n/dictionaries.ts` as flat objects keyed by `en` and `zh`.
- `useI18n()` returns `{ t, locale, setLocale }`. `t(key, values?)` supports simple interpolation for dynamic fragments like `last {count}`.
- The initial locale defaults to the browser language (`navigator.language`) when no saved preference exists.
- `document.documentElement.lang` is updated when the locale changes.
- A `LanguageSwitcher` component in the topbar switches between `en` and `zh`.

### 3. UI string replacement

All hard-coded labels, placeholders, button text, notices, and option labels in `App.tsx`, `AdvancedSettings.tsx`, and `FullscreenTextEditor.tsx` are replaced with `t(...)` calls.

Keys are organized by feature area, e.g.:

- `brand.title`, `brand.subtitle`
- `nav.tts`, `nav.asr`
- `tts.mode.builtin`, `tts.voice`, `tts.stylePrompt`
- `asr.audioFile`, `asr.language`
- `history.title`, `history.empty`
- `theme.light`, `theme.dark`, `theme.system`
- `lang.en`, `lang.zh`

### 4. Topbar controls

The existing `.topbar` gains a `.topbar-controls` group on the right containing:

- `LanguageSwitcher` (text buttons `EN` / `中文`).
- `ThemeToggle` (icon + label for the current mode).

Controls use the existing `.btn-ghost` and `.select-input` styling and collapse gracefully on mobile.

### 5. Persistence keys

- `voice-toolbox-locale`
- `voice-toolbox-theme`

### 6. Testing & verification

- TypeScript dictionaries are fully typed so missing translations become compile errors.
- No new runtime dependencies are added.
- After implementation, run `make check` to ensure backend and frontend tests, lint, format, and build all pass.
