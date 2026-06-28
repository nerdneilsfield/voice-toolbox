# Voice Toolbox UI Redesign

Date: 2026-06-28

## Summary

Redesign the Voice Toolbox web UI (`apps/web/`) to improve visual hierarchy, layout balance, and component consistency. The redesign keeps all existing functionality intact and adds one new backend endpoint (`GET /v1/artifacts`) to support a frontend history panel.

The chosen direction is **Indigo Studio Sidebar**: a three-column workbench layout with a left navigation sidebar for TTS modes and ASR, a central editing canvas with grouped cards, and a fixed right-side output panel. The visual treatment uses an Indigo AI color palette, soft shadows, rounded cards, and a unified button hierarchy.

## Goals

- Replace the current two-column tabbed layout with a clearer studio-style sidebar navigation.
- Establish a consistent button hierarchy (primary, secondary, tertiary, icon-only).
- Unify text editor actions (char count + fullscreen expand) into a single, repeatable pattern in each section heading.
- Reduce visual noise by replacing heavy borders with subtle shadows and tinted borders on white cards.
- Improve the output panel so audio controls, format selection, and download actions feel grouped and scannable.
- Keep the implementation within the existing React + Vite + plain CSS stack; no new dependencies.
- Maintain responsive behavior down to mobile widths.
- Add a history list in the output panel showing recent TTS/ASR artifacts, backed by a new backend listing endpoint.

## Non-Goals

- No new pages or routes; it remains a single-page app.
- No changes to existing backend endpoints, API contracts, or data models (only one new read-only endpoint is added).
- No new animation libraries; motion stays limited to CSS transitions.
- No dark mode in this iteration.
- No redesign of the fullscreen text editor modal beyond styling alignment.

## Current State

The current UI (`apps/web/src/App.tsx`, `apps/web/src/styles.css`) uses:

- A top header with a large title and a provider pill on the right.
- A horizontal provider details strip (Env / Key / Base URL / Config) directly under the header.
- TTS/ASR tabs rendered as a segmented control.
- A two-column grid (`1.28fr / 0.72fr`) with a form panel on the left and a result panel on the right.
- Multiple section headings with inconsistent placement of `chars` / `Fullscreen` actions.
- Tags rendered as secondary buttons; custom tag as a two-column input+button.
- Full-width primary action with a meta row directly above it.

Pain points observed:

- Provider details strip competes with the main content for attention.
- Output panel feels narrow and cramped.
- `Fullscreen` buttons appear above some textareas and below others.
- Too many border styles and font sizes create visual clutter.
- Tags look like actions rather than inline inserts.

## Proposed Design

### Layout

```
+-------------------------------------------------------------+
|  Logo  Voice Toolbox          [Provider ▾] [API key status] |
|  Env: ...  Base URL: ...  Config: ...                       |
+----------+--------------------------------+---------------+
|          |                                |               |
|  TTS     |  [Text format card]            |               |
|  ├── B-in|                                |    Output     |
|  ├── Des |  [Voice persona card]          |    [player]   |
|  └── Clo |                                |    [download] |
|          |  [Script card]                 |               |
|  ASR     |    [tag chips...]              |               |
|  └── Tra |                                |               |
|          |  [Model / format meta card]    |               |
|          |                                |               |
|          |  [Generate voice]              |               |
|          |                                |               |
+----------+--------------------------------+---------------+
```

- **Header**: Logo + title/subtitle on the left; provider selector and key status on the right.
- **Provider strip**: Moved below the header but styled subtly (small, muted, no heavy separators).
- **Sidebar (190px)**: TTS modes (Built-in, Design, Clone) and ASR (Transcribe) as vertical navigation items. Active item uses indigo-tinted background.
- **Center canvas**: Stacked cards for Text format, Voice persona, Script, Model/Format meta, and the primary action.
- **Right output panel (320px)**: Fixed-width, sticky-top if content is long, containing Output heading, audio player, download format + button, and artifact meta.

### Visual Design System

**Colors**

| Token | Value | Usage |
|-------|-------|-------|
| `--accent` | `#4f46e5` | Primary buttons, active sidebar item, links |
| `--accent-hover` | `#4338ca` | Button hover, active states |
| `--accent-soft` | `#eef2ff` | Active backgrounds, badges, pills |
| `--accent-border` | `#e0e7ff` | Card borders, secondary button borders |
| `--accent-muted` | `#a5b4fc` | Uppercase labels, secondary text |
| `--bg-base` | `#f8fafc` | Page background |
| `--bg-elevated` | `#ffffff` | Cards, panels |
| `--bg-sunken` | `#f1f5f9` | Input/textarea backgrounds |
| `--text` | `#1e1b4b` | Headings, primary text |
| `--text-body` | `#374151` | Body text in inputs |
| `--muted` | `#64748b` | Secondary text, labels |
| `--border` | `#e2e8f0` | Subtle dividers |

**Typography**

- Headings: 1rem, font-weight 800, color `--text`.
- Section labels: 0.72rem, uppercase, font-weight 900, color `--accent-muted`, letter-spacing 0.05em.
- Body/inputs: 0.85rem, line-height 1.6, color `--text-body`.
- Meta text: 0.75rem, color `--muted`.

**Spacing**

- Page padding: 24px horizontal, 20px between grid columns.
- Card padding: 18px.
- Card gap: 16px vertical.
- Card radius: 12px.
- Small radius (inputs, buttons): 8px / 6px.

**Shadows**

- Cards: `0 1px 3px rgba(79, 70, 229, 0.06)`.
- Primary button hover: `0 4px 14px rgba(79, 70, 229, 0.28)`.

### Component Changes

#### Header

- Add a 32×32 rounded gradient logo mark (`linear-gradient(135deg, #4f46e5, #6366f1)`).
- Keep title/subtitle stacked but use tighter line height.
- Provider selector styled as a select with indigo-tinted text and border.
- Key status as a pill badge (`--accent-soft` background, `--accent-hover` text).

#### Provider Strip

- Remove the vertical separators and uppercase labels from the current version.
- Use small uppercase labels (`Env`, `Base URL`, `Config`) in `--accent-muted` followed by values in `--muted`.
- Background stays white; border-bottom uses `--accent-border`.

#### Sidebar

- Section headers: `TTS`, `ASR` in tiny uppercase indigo-muted text.
- Nav items: 8px 10px padding, 8px radius, flex row with icon + label.
- Active item: `--accent-soft` background, `--accent-hover` text, font-weight 800.
- Inactive item: transparent background, `--muted` text.
- Icons are emoji placeholders in v1; can be replaced with SVG icons later without layout changes.

#### Cards

- Every functional block becomes a white card with `--accent-border` border and subtle shadow.
- Card header: section label on the left, actions/meta on the right.
- Inputs/textareas use `--bg-sunken` background and sit flush inside the card.

#### Button Hierarchy

| Type | Style | Usage |
|------|-------|-------|
| Primary | Filled `--accent`, white text, 10px radius, shadow | Generate voice, Transcribe, Preview, Download |
| Secondary | White background, `--accent-border` border, `--accent-hover` text | Toggled options, outline actions |
| Tertiary / Chip | `--accent-soft` background, `--accent-hover` text, pill radius | Audio tags |
| Icon / Link | Transparent or minimal, `--accent-hover` text | Fullscreen expand (↗) |

#### Text Editor Actions

- Applied only to cards that contain a textarea (TTS script, voice persona, clone reference text).
- Always placed in the card header on the right.
- Pattern: `[char count] [icon-only expand button]`.
- Remove the old `TextEditorActions` component that rendered count below some textareas and fullscreen above others.

#### Audio Tags

- Render tags as small pill chips (`tertiary` style).
- Custom tag input becomes a small inline input with pill styling on the same row, placeholder "+ tag".
- Submit the custom tag by pressing Enter; no separate Insert button.

#### Output Panel

- Fixed 320px width; sticky at top if center canvas is taller.
- Heading row: "Output" + format pill.
- Audio player full width with rounded corners.
- Download row: format select (secondary) + download button (primary) side by side.
- Artifact meta below in muted text.
- Empty state keeps the waveform animation but inside the card.

#### History Panel

- Located below the current Output card in the right column.
- Heading row: "History" + a muted "last N" count.
- Each item shows:
  - Operation type and mode (e.g., "TTS • Built-in", "ASR • Transcribe").
  - Timestamp.
  - A text action button ("Play" for audio, "View" for transcripts) that loads the artifact into the current Output card.
- v1 reads only sidecar metadata; audio duration and transcript previews are deferred to a future iteration.
- Items are loaded from the backend on mount and refreshed after each successful generation/transcription.
- Maximum list length: 20 items by default, configurable via query parameter.

### Backend Addition

A new endpoint is required to support the history panel:

- `GET /v1/artifacts?limit=20`
  - Returns a list of recent artifacts sorted by `created_at` descending.
  - Each entry contains: `id`, `operation`, `kind`, `mime_type`, `created_at`.
  - Implementation scans only the artifact sidecar directory (`data/artifacts/*/*.json`) and returns validated summaries; it does not read artifact files in v1.

### Responsive Behavior

- **Desktop (>1024px)**: Full three-column layout; the output panel is `position: sticky` at the top.
- **Tablet (820px–1024px)**: Collapse the output panel below the center canvas and remove sticky positioning so it flows in document order.
- **Mobile (<820px)**:
  - Sidebar becomes a horizontal mode selector at the top.
  - Cards stack vertically.
  - Output panel appears below the form after generation.

## Files to Modify

- `apps/web/src/styles.css`: Replace design tokens and layout classes.
- `apps/web/src/App.tsx`: Refactor layout structure, sidebar navigation, card wrappers, button styles, and text editor actions.
- `apps/web/src/components/FullscreenTextEditor.tsx`: Update expand button usage (icon-only) and modal styling alignment.
- `apps/web/src/components/AdvancedSettings.tsx`: Minor styling alignment for the details/summary within cards.
- `apps/web/src/api.ts`: Add `getArtifacts(limit)` to call the new listing endpoint.
- `apps/api/src/voice_toolbox_api/main.py`: Add `GET /v1/artifacts` listing endpoint and helper to read sidecars safely.

No new dependencies are required.

## Testing

- Run `cd apps/web && bun run test` to confirm TypeScript and unit tests pass.
- Run `cd apps/web && bun run build` to confirm production build succeeds.
- Manual checks:
  - All four modes (TTS built-in, TTS design, TTS clone, ASR) render correctly.
  - Provider switching updates the sidebar active state and available models.
  - Generate voice / transcribe produce output in the right panel.
  - Fullscreen editor opens and applies text changes.
  - Audio tags insert correctly and custom tag submits on Enter.
  - Responsive breakpoints collapse gracefully.
  - `GET /v1/artifacts` returns recent artifacts sorted by time.
  - History panel populates on load and updates after each new generation/transcription.
  - Clicking a history item loads it into the Output card.

## Open Questions / Notes

- Sidebar icons are emoji placeholders. A future iteration can introduce a small SVG icon set without changing layout.
- The provider details strip could be further collapsed into a footer or tooltip if it still feels noisy after implementation.
- This redesign intentionally stays in light mode; dark mode is out of scope.
