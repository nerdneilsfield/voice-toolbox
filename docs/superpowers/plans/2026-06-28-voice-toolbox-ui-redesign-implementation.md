# Voice Toolbox UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Voice Toolbox web UI into an Indigo Studio Sidebar layout with grouped cards, unified buttons, and a history panel backed by a new backend artifact listing endpoint.

**Architecture:** A new read-only `GET /v1/artifacts` endpoint returns recent artifact sidecars. The React frontend fetches this list and renders it below the output panel. All existing TTS/ASR functionality remains unchanged; only layout, styling, and the history feature are added.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, React 19, TypeScript, Vite, plain CSS, bun.

## Global Constraints

- No new dependencies in `apps/web/package.json`.
- No new animation libraries; motion stays limited to CSS transitions.
- No dark mode in this iteration.
- No changes to existing backend endpoints, API contracts, or data models (only one new read-only endpoint is added).
- History v1 reads only sidecar metadata; audio duration and transcript previews are deferred.
- Responsive breakpoints: desktop three-column (>1024px), tablet stacked output (820px–1024px), mobile stacked with horizontal mode selector (<820px).

---

## File Structure

- `apps/api/src/voice_toolbox_api/main.py`: Add `GET /v1/artifacts` and refactor sidecar reading into a path-based helper.
- `apps/web/src/api.ts`: Add `getArtifacts(limit)` function.
- `apps/web/src/styles.css`: Replace design tokens and layout classes with the Indigo Studio Sidebar theme.
- `apps/web/src/App.tsx`: Refactor layout structure, sidebar navigation, card wrappers, button styles, and text editor actions.
- `apps/web/src/components/FullscreenTextEditor.tsx`: Update expand button to accept an icon-only trigger and align modal styling.
- `apps/web/src/components/AdvancedSettings.tsx`: Minor styling alignment for the details/summary within cards.
- `tests/test_api.py`: Add a test for the new listing endpoint.

---

## Task 1: Backend Artifact Listing Endpoint

**Files:**
- Modify: `apps/api/src/voice_toolbox_api/main.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: existing `_safe_artifact_payload`, `Artifact`, sidecar JSON files in `data/artifacts/*/*.json`.
- Produces: `GET /v1/artifacts?limit=20` returning `{"artifacts": [...]}` sorted by `created_at` descending.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api.py`:

```python
def test_list_artifacts(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    artifact_root = tmp_path / "data" / "artifacts"
    artifact_root.mkdir(parents=True)
    op_dir = artifact_root / "20260628"
    op_dir.mkdir()
    sidecars = [
        {
            "id": "test-artifact-1",
            "provider_id": "mimo",
            "operation": "tts",
            "kind": "audio",
            "mime_type": "audio/wav",
            "created_at": "2026-06-28T12:00:00+00:00",
            "path": "test1.wav",
            "metadata": {"tts_mode": "builtin"},
        },
        {
            "id": "test-artifact-2",
            "provider_id": "mimo",
            "operation": "asr",
            "kind": "transcript",
            "mime_type": "text/plain; charset=utf-8",
            "created_at": "2026-06-28T13:00:00+00:00",
            "path": "test2.txt",
        },
        {
            "id": "test-artifact-3",
            "provider_id": "mimo",
            "operation": "tts",
            "kind": "audio",
            "mime_type": "audio/wav",
            "created_at": "2026-06-28T11:00:00+00:00",
            "path": "test3.wav",
            "metadata": {"tts_mode": "design"},
        },
    ]
    for sidecar in sidecars:
        (op_dir / f"{sidecar['id']}.json").write_text(json.dumps(sidecar))

    response = client.get("/v1/artifacts?limit=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["artifacts"]) == 2
    assert data["artifacts"][0]["id"] == "test-artifact-2"  # newest first
    assert data["artifacts"][1]["id"] == "test-artifact-1"


def test_list_artifacts_empty_root(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get("/v1/artifacts")
    assert response.status_code == 200
    assert response.json() == {"artifacts": []}


def test_list_artifacts_skips_invalid_sidecars(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    artifact_root = tmp_path / "data" / "artifacts"
    artifact_root.mkdir(parents=True)
    op_dir = artifact_root / "20260628"
    op_dir.mkdir()
    (op_dir / "bad.json").write_text("not json")
    response = client.get("/v1/artifacts")
    assert response.status_code == 200
    assert response.json() == {"artifacts": []}


def test_list_artifacts_limit_validation(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/v1/artifacts?limit=0").status_code == 422
    assert client.get("/v1/artifacts?limit=101").status_code == 422


class MetadataStrippingProvider(RecordingMimoProvider):
    """Proves _run_tts injects tts_mode itself. This provider bypasses
    FakeProvider.synthesize (which would add tts_mode from request.mode) and
    persists ONLY the injected artifact_metadata, so the only way tts_mode can
    appear in the sidecar is the _run_tts injection."""

    def synthesize(self, request, *, artifact_metadata=None):
        self.tts_requests.append(request)
        self._ensure_open()
        operation_id = self._next_operation_id("tts")
        return self._artifact_store.write_audio(
            operation_id=operation_id,
            provider_id=self.id,
            operation="tts",
            audio=self._audio_bytes(request),
            metadata=dict(artifact_metadata or {}),
        )


def test_tts_mode_persisted_in_artifact_metadata(tmp_path: Path) -> None:
    """_run_tts injects tts_mode into artifact_metadata before synthesize, so the
    listing endpoint can label each artifact even when the provider omits it."""
    provider = MetadataStrippingProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={"MIMO_API_KEY": "test-key"},
    )
    client = TestClient(app)

    builtin_response = client.post(
        "/v1/tts/builtin",
        data={"provider_id": "mimo", "text": "hello world", "voice_id": "Mia"},
    )
    assert builtin_response.status_code == 200
    builtin_id = builtin_response.json()["artifact"]["id"]

    listed = client.get("/v1/artifacts").json()["artifacts"]
    by_id = {item["id"]: item for item in listed}
    assert by_id[builtin_id]["metadata"]["tts_mode"] == "builtin"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox && pytest tests/test_api.py::test_list_artifacts -v
```

Expected: FAIL with "404 Not Found" because the endpoint does not exist.

- [ ] **Step 3: Refactor sidecar reading into a path-based helper**

In `apps/api/src/voice_toolbox_api/main.py`, replace `_read_artifact_sidecar` and add `_read_artifact_sidecar_path`:

```python
def _read_artifact_sidecar(root: Path, artifact_id: str) -> Artifact:
    if not SAFE_OPERATION_ID_PATTERN.fullmatch(artifact_id):
        raise HTTPException(status_code=404, detail="artifact not found")
    artifact_root = (root / "data" / "artifacts").resolve(strict=False)
    matches = sorted(artifact_root.glob(f"*/{artifact_id}.json"))
    if not matches:
        raise HTTPException(status_code=404, detail="artifact not found")
    artifact = _read_artifact_sidecar_path(matches[-1], root)
    if artifact.id != artifact_id:
        raise HTTPException(status_code=422, detail="artifact sidecar id mismatch")
    return artifact


def _read_artifact_sidecar_path(sidecar_path: Path, root: Path) -> Artifact:
    artifact_root = (root / "data" / "artifacts").resolve(strict=False)
    # Resolve before any read so symlink/relative-glob cases are normalized once.
    resolved_sidecar = sidecar_path.resolve(strict=False)
    if not resolved_sidecar.is_relative_to(artifact_root):
        raise HTTPException(status_code=422, detail="artifact sidecar is outside artifact root")
    try:
        with resolved_sidecar.open(encoding="utf-8") as sidecar_file:
            payload = json.load(sidecar_file)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="artifact sidecar is invalid") from exc
    if "path" not in payload:
        payload["path"] = str(_artifact_path_for_sidecar(resolved_sidecar, payload))
    try:
        artifact = Artifact.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="artifact sidecar is invalid") from exc
    raw_path = artifact.path
    path = (
        (resolved_sidecar.parent / raw_path).resolve(strict=False)
        if not raw_path.is_absolute()
        else raw_path.resolve(strict=False)
    )
    if not path.is_relative_to(artifact_root):
        raise HTTPException(status_code=422, detail="artifact path is outside artifact root")
    return artifact.model_copy(update={"path": path})
```

**Behavior note:** the ID-mismatch check (`artifact.id != artifact_id`) stays in `_read_artifact_sidecar` so the existing `GET /v1/artifacts/{id}` and `/download` routes keep their 422-on-mismatch contract. The new `_read_artifact_sidecar_path` is shared by both the per-id reader and the listing endpoint, and is exercised by the existing `test_artifact_metadata_and_download_read_sidecar` plus the new listing tests below.

- [ ] **Step 4: Add the listing endpoint**

Insert this route in `apps/api/src/voice_toolbox_api/main.py` before the existing `GET /v1/artifacts/{artifact_id}` route:

```python
@app.get("/v1/artifacts")
def list_artifacts(
    http_request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, list[dict[str, Any]]]:
    root = http_request.app.state.artifact_root
    artifact_root = (root / "data" / "artifacts").resolve(strict=False)
    if not artifact_root.exists():
        return {"artifacts": []}
    sidecars = sorted(artifact_root.glob("*/*.json"))
    artifacts: list[Artifact] = []
    for sidecar_path in sidecars:
        try:
            artifacts.append(_read_artifact_sidecar_path(sidecar_path, root))
        # Listing is intentionally lenient: a single corrupt/malformed sidecar
        # must not 500 the whole list. All per-sidecar failures (invalid JSON,
        # schema validation, path-escape guard, IO errors) are logged and skipped.
        except (HTTPException, ValidationError, json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("skipping unreadable artifact sidecar: {} - {}", sidecar_path, exc)
            continue
    artifacts.sort(key=lambda artifact: artifact.created_at, reverse=True)
    return {"artifacts": [_safe_artifact_payload(artifact) for artifact in artifacts[:limit]]}
```

- [ ] **Step 5: Ensure TTS mode is recorded in artifact metadata**

In `apps/api/src/voice_toolbox_api/main.py`, update `_run_tts` so the generated artifact metadata includes the TTS mode for history labels. Inject the mode **before** calling `provider.synthesize` so it is persisted to the sidecar. Use copy-and-update rather than mutating `prepared.artifact_metadata` in place, so the injection is independent of whether the caller's mapping is mutable or shared:

```python
mode_metadata = {
    **(prepared.artifact_metadata or {}),
    "tts_mode": prepared.request.mode.value,
}

artifact = provider.synthesize(
    prepared.request,
    artifact_metadata=mode_metadata,
)
```

`prepared.artifact_metadata` is currently a fresh `dict` per request (`pipeline.PreparedTTSRequest.artifact_metadata`), so the spread is defensive — it keeps the injection correct if that field ever becomes frozen or a shared mapping, and it never clobbers provider-side keys like `clone_base64_size` (those are merged by the provider from `request`, not from `artifact_metadata`).

- [ ] **Step 6: Run the tests to verify they pass**

Run:

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox && uv run pytest tests/test_api.py::test_list_artifacts tests/test_api.py::test_list_artifacts_empty_root tests/test_api.py::test_list_artifacts_skips_invalid_sidecars tests/test_api.py::test_list_artifacts_limit_validation -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox
git add apps/api/src/voice_toolbox_api/main.py tests/test_api.py
git commit -m "feat(api): add GET /v1/artifacts listing endpoint"
```

---

## Task 2: Frontend API Client for History

**Files:**
- Modify: `apps/web/src/api.ts`

**Interfaces:**
- Consumes: `Artifact` type already defined in `apps/web/src/api.ts`.
- Produces: `getArtifacts(limit?: number): Promise<Artifact[]>`.

- [ ] **Step 1: Add the history API function**

In `apps/web/src/api.ts`, add after the existing artifact-related functions:

```typescript
export async function getArtifacts(limit = 20): Promise<Artifact[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  const data = await requestJson<{ artifacts: Artifact[] }>(`/v1/artifacts?${params}`);
  return data.artifacts;
}
```

- [ ] **Step 2: Add a test for `getArtifacts`**

In `apps/web/src/api.test.ts`, add `getArtifacts` to the existing `./api` import:

```typescript
import { getArtifacts, synthesizeBuiltin } from "./api";
```

Then add these tests inside the existing `describe("api client", () => { ... })` block:

```typescript
it("fetches artifacts with limit", async () => {
  const mockArtifact = {
    id: "test-1",
    provider_id: "mimo",
    operation: "tts",
    kind: "audio",
    mime_type: "audio/wav",
    created_at: "2026-06-28T12:00:00+00:00",
    download_url: "/v1/artifacts/test-1/download",
  };
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ artifacts: [mockArtifact] }), {
      headers: { "content-type": "application/json" },
    }),
  );

  const artifacts = await getArtifacts(10);

  expect(globalThis.fetch).toHaveBeenCalledWith("/v1/artifacts?limit=10");
  expect(artifacts).toEqual([mockArtifact]);
});

it("throws on non-ok response", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("Server error", { status: 500 }));

  await expect(getArtifacts()).rejects.toThrow("Server error");
});
```

- [ ] **Step 3: Verify tests pass**

Run:

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox/apps/web && bun run test
```

Expected: `tsc --noEmit` and `vitest run` pass.

- [ ] **Step 4: Commit**

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox
git add apps/web/src/api.ts apps/web/src/api.test.ts
git commit -m "feat(web): add getArtifacts client for history panel"
```

---

## Task 3: Replace Design Tokens and Base CSS

**Files:**
- Modify: `apps/web/src/styles.css`

**Interfaces:**
- Consumes: Existing HTML structure will be replaced in Task 4; CSS classes must match the new class names used there.
- Produces: A complete set of utility classes for the Indigo Studio Sidebar theme.

- [ ] **Step 1: Replace the design tokens and base reset section**

Replace the `:root` block and the base reset rules in `apps/web/src/styles.css` with:

```css
:root {
  --accent: #4f46e5;
  --accent-hover: #4338ca;
  --accent-soft: #eef2ff;
  --accent-border: #e0e7ff;
  --accent-muted: #818cf8;
  --bg-base: #f8fafc;
  --bg-elevated: #ffffff;
  --bg-sunken: #f1f5f9;
  --text: #1e1b4b;
  --text-body: #374151;
  --muted: #475569;
  --border: #e2e8f0;
  --danger: #b42318;
  --danger-soft: #fff1f0;
  --warning: #8a4d00;
  --warning-soft: #fff7e6;
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --shadow-card: 0 1px 3px rgba(79, 70, 229, 0.06);
  --shadow-button: 0 4px 14px rgba(79, 70, 229, 0.28);
  /* Compatibility aliases for old tokens still referenced during migration */
  --accent-strong: var(--accent-hover);
  --bg-quiet: var(--bg-sunken);
  --border-strong: var(--accent-border);
  --muted-strong: var(--muted);
  --shadow-sm: var(--shadow-card);
  color: var(--text);
  background: var(--bg-base);
  font-family:
    Inter,
    "PingFang SC",
    "Noto Sans SC",
    ui-sans-serif,
    system-ui,
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
  font-synthesis: none;
  line-height: 1.6;
  text-rendering: optimizeLegibility;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 320px;
  background: var(--bg-base);
}

button,
input,
select,
textarea {
  font: inherit;
}

button {
  cursor: pointer;
}

/* Base cursor for any disabled control; themed buttons (.btn-*, .primary-action)
   add opacity/box-shadow overrides in their own rules below. */
button:disabled {
  cursor: not-allowed;
}

h1,
h2,
p {
  margin: 0;
}
```

- [ ] **Step 2: Add the new layout classes**

Append the following layout classes to `apps/web/src/styles.css`. Keep existing component classes only if they are still used; otherwise remove or replace them incrementally as you refactor `App.tsx`.

```css
.app-shell {
  width: min(1280px, calc(100vw - 48px));
  margin: 0 auto;
  padding: 24px 0 48px;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 16px 0;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--accent-border);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--accent), #6366f1);
  display: grid;
  place-items: center;
  color: #fff;
  font-weight: 900;
}

.brand-title {
  font-size: 1rem;
  font-weight: 800;
  letter-spacing: -0.01em;
  line-height: 1.2;
}

.brand-subtitle {
  font-size: 0.72rem;
  color: var(--muted);
}

.provider-strip {
  display: flex;
  align-items: center;
  gap: 8px;
}

.provider-strip select {
  width: auto;
  min-width: 130px;
  font-size: 0.82rem;
  padding: 6px 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--accent-border);
  background: var(--bg-elevated);
  color: var(--accent-hover);
}

.status-badge {
  font-size: 0.75rem;
  color: var(--accent-hover);
  background: var(--accent-soft);
  padding: 5px 10px;
  border-radius: 999px;
  font-weight: 700;
}

.status-badge.ok {
  color: #166534;
  background: #dcfce7;
}

.status-badge.warn {
  color: #991b1b;
  background: #fee2e2;
}

.provider-details {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  padding: 8px 0;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--accent-border);
  font-size: 0.72rem;
  color: var(--muted);
}

.provider-details span.label {
  font-weight: 800;
  text-transform: uppercase;
  color: var(--accent-muted);
  letter-spacing: 0.05em;
}

.workspace {
  display: grid;
  grid-template-columns: 190px 1fr 320px;
  gap: 20px;
  padding: 20px 0;
  align-items: start;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.sidebar-section {
  font-size: 0.68rem;
  font-weight: 900;
  text-transform: uppercase;
  color: var(--accent-muted);
  letter-spacing: 0.05em;
  margin-bottom: 8px;
  padding-left: 10px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--muted);
  cursor: pointer;
  border: 0;
  background: transparent;
}

.nav-item.active {
  background: var(--accent-soft);
  color: var(--accent-hover);
  font-weight: 800;
}

.canvas {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card {
  background: var(--bg-elevated);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-lg);
  padding: 18px;
  box-shadow: var(--shadow-card);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  gap: 12px;
}

.card-label {
  font-size: 0.78rem;
  font-weight: 900;
  text-transform: uppercase;
  color: var(--accent-muted);
  letter-spacing: 0.05em;
}

.card-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.char-count {
  font-size: 0.75rem;
  color: #94a3b8;
  font-weight: 700;
}

.expand-link {
  display: inline-grid;
  place-items: center;
  min-width: 28px;
  min-height: 28px;
  font-size: 0.85rem;
  color: var(--accent);
  background: transparent;
  border: 0;
  border-radius: var(--radius-sm);
  padding: 2px 4px;
  font-weight: 700;
  cursor: pointer;
}

.text-input,
.script-input {
  width: 100%;
  border: 0;
  border-radius: var(--radius-md);
  background: var(--bg-sunken);
  color: var(--text-body);
  padding: 12px;
  font-size: 0.85rem;
  line-height: 1.6;
  outline: none;
  resize: vertical;
}

.text-input {
  min-height: 0;
}

.script-input {
  min-height: 80px;
  resize: vertical;
  line-height: 1.6;
}

.text-input:focus,
.script-input:focus {
  box-shadow: 0 0 0 2px var(--accent-border);
}

.select-input {
  width: auto;
  font-size: 0.82rem;
  padding: 5px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--accent-border);
  background: var(--bg-elevated);
  color: var(--accent-hover);
  outline: none;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 0;
  border-radius: var(--radius-sm);
  font-weight: 700;
  font-size: 0.82rem;
  cursor: pointer;
  transition: background 160ms ease, box-shadow 160ms ease;
}

.btn-primary {
  background: var(--accent);
  color: #fff;
  padding: 6px 12px;
  box-shadow: none;
}

.btn-primary:hover {
  background: var(--accent-hover);
  box-shadow: var(--shadow-button);
}

.btn-primary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
}

.btn-secondary {
  background: var(--bg-elevated);
  color: var(--accent-hover);
  border: 1px solid var(--accent-border);
  padding: 5px 10px;
}

.btn-secondary:hover {
  background: var(--accent-soft);
}

.btn-secondary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn-ghost {
  display: inline-grid;
  place-items: center;
  min-width: 28px;
  min-height: 28px;
  background: transparent;
  color: var(--accent);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
}

.btn-ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.chip {
  display: inline-grid;
  place-items: center;
  min-height: 24px;
  font-size: 0.72rem;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent-hover);
  font-weight: 700;
  border: 0;
  cursor: pointer;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
  align-items: center;
}

.tag-input {
  width: 90px;
  min-height: 24px;
  font-size: 0.72rem;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid var(--accent-border);
  background: var(--bg-elevated);
  outline: none;
}

.meta-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.meta-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 0.78rem;
  color: var(--muted);
}

.meta-label > span:first-child {
  font-weight: 800;
  text-transform: uppercase;
  color: var(--accent-muted);
  letter-spacing: 0.05em;
}

.format-pill {
  font-size: 0.72rem;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent-hover);
  font-weight: 800;
}

.primary-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  min-height: 48px;
  padding: 12px;
  border-radius: var(--radius-md);
  background: var(--accent);
  color: #fff;
  font-weight: 900;
  font-size: 0.95rem;
  border: 0;
  cursor: pointer;
  transition: background 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.primary-action:hover {
  background: var(--accent-hover);
  box-shadow: var(--shadow-button);
  transform: translateY(-1px);
}

.primary-action:disabled {
  opacity: 0.62;
  cursor: not-allowed;
  transform: none;
}

.output-panel {
  position: sticky;
  top: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.history-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  background: var(--bg-sunken);
}

.history-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.history-title {
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--text-body);
}

.history-time {
  font-size: 0.7rem;
  color: #94a3b8;
}

.empty-state {
  min-height: 180px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 16px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-sunken);
  color: var(--muted);
  font-weight: 800;
}

.notice {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-sunken);
  color: var(--muted);
  padding: 10px 12px;
}

.notice.error {
  border-color: #fecdca;
  background: var(--danger-soft);
  color: var(--danger);
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.44);
  border-top-color: #fff;
  border-radius: 999px;
  animation: spin 700ms linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1024px) {
  .workspace {
    grid-template-columns: 190px 1fr;
  }

  .output-panel {
    position: static;
    grid-column: 1 / -1;
    max-height: none;
    overflow-y: visible;
  }
}

@media (max-width: 819px) {
  .app-shell {
    width: min(100vw - 20px, 1280px);
    padding-top: 14px;
  }

  .topbar {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .provider-strip {
    justify-content: flex-start;
  }

  .workspace {
    grid-template-columns: 1fr;
  }

  .sidebar {
    flex-direction: row;
    flex-wrap: wrap;
    gap: 8px;
  }

  .sidebar > div {
    display: contents;
  }

  .sidebar-section {
    display: none;
  }

  .nav-item {
    flex: 1 1 auto;
    justify-content: center;
  }
}
```

- [ ] **Step 3: Verify the CSS compiles**

Run:

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox/apps/web && bun run build
```

Expected: The build succeeds. Fix any missing CSS variables or syntax errors before proceeding.

- [ ] **Step 4: Add compatibility classes for existing components**

Append the following rules to `apps/web/src/styles.css` so existing components (`ResultPanel`, `TranscriptPanel`, `EmptyState`, `LoadingState`, `TextTools`, etc.) continue to render with the Indigo theme:

```css
/* Result / transcript panels */
.result-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.result-heading h2 {
  font-size: 1rem;
  font-weight: 800;
  color: var(--text);
}

.artifact-block {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.audio-player {
  width: 100%;
  border-radius: 999px;
}

.result-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.download-format {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 0.82rem;
  font-weight: 700;
}

.download-link {
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #fff;
  font-weight: 800;
  font-size: 0.82rem;
  text-decoration: none;
}

.download-link:hover {
  background: var(--accent-hover);
}

.artifact-meta {
  color: var(--accent-muted);
  font-size: 0.75rem;
  font-weight: 700;
}

.transcript-toolbar {
  display: flex;
  justify-content: flex-end;
}

.transcript-toolbar button {
  padding: 5px 10px;
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-sm);
  background: var(--bg-elevated);
  color: var(--accent-hover);
  font-weight: 700;
  font-size: 0.82rem;
}

.transcript-viewer {
  min-height: 220px;
  max-height: 480px;
  margin: 0;
  overflow: auto;
  white-space: pre-wrap;
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-md);
  background: var(--bg-sunken);
  color: var(--text-body);
  padding: 14px;
  line-height: 1.65;
}

/* Empty / loading states */
.waveform {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 48px;
}

.waveform span {
  width: 8px;
  border-radius: 999px;
  background: var(--accent);
}

.waveform span:nth-child(1) { height: 18px; }
.waveform span:nth-child(2) { height: 34px; }
.waveform span:nth-child(3) { height: 48px; }
.waveform span:nth-child(4) { height: 30px; }
.waveform span:nth-child(5) { height: 22px; }

.loading-state {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 10px 0;
}

.loading-state span {
  height: 18px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--bg-sunken) 0%, var(--bg-elevated) 45%, var(--bg-sunken) 100%);
  background-size: 200% 100%;
  animation: shimmer 1100ms ease-in-out infinite;
}

.loading-state span:nth-child(1) { width: 84%; }
.loading-state span:nth-child(2) { width: 100%; }
.loading-state span:nth-child(3) { width: 62%; }
.loading-state span:nth-child(4) { width: 74%; }

@keyframes shimmer {
  to { background-position: -200% 0; }
}

/* Text tools */
.text-tools {
  display: contents;
}

.text-tools-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
}

.text-format-field {
  flex: 0 1 280px;
}

.preview-action {
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #fff;
  font-weight: 700;
  font-size: 0.8rem;
  border: 0;
}

.cleaned-preview {
  max-height: 180px;
  margin: 0;
  overflow: auto;
  white-space: pre-wrap;
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-md);
  background: var(--bg-elevated);
  color: var(--text-body);
  padding: 12px;
  line-height: 1.55;
}

/* Misc */
.notice.compact {
  font-size: 0.9rem;
}

.modal-overlay {
  position: fixed;
  z-index: 50;
  inset: 0;
  display: grid;
  background: rgba(30, 27, 75, 0.55);
  padding: 18px;
}

.fullscreen-editor {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 14px;
  width: min(1100px, 100%);
  height: min(860px, 100%);
  margin: auto;
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-lg);
  background: var(--bg-elevated);
  padding: 18px;
  box-shadow: 0 24px 80px rgba(30, 27, 75, 0.28);
}

.fullscreen-editor__header,
.fullscreen-editor__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.fullscreen-editor__textarea {
  min-height: 0;
  height: 100%;
  resize: none;
  line-height: 1.7;
}

/* Legacy panel wrappers used during migration */
.result-panel,
.tool-panel {
  background: var(--bg-elevated);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-lg);
  padding: 18px;
  box-shadow: var(--shadow-card);
}

/* Status item for provider strip */
.status-item {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 0.72rem;
  color: var(--muted);
}

.status-item .label {
  font-weight: 800;
  text-transform: uppercase;
  color: var(--accent-muted);
  letter-spacing: 0.05em;
}

.status-item strong {
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: min(360px, 70vw);
}

/* Base form controls */
input[type="text"],
input[type="file"],
select,
textarea {
  font: inherit;
  width: 100%;
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-md);
  background: var(--bg-sunken);
  color: var(--text-body);
  padding: 10px 12px;
  outline: none;
}

input:focus,
select:focus,
textarea:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.18);
}

button:focus-visible,
.chip:focus-visible,
.expand-link:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.28);
}

.field {
  display: grid;
  gap: 8px;
  color: var(--muted);
  font-size: 0.92rem;
  font-weight: 700;
}

.field-title {
  color: var(--muted);
}

/* Switch/checkbox lines */
.switch-line,
.checkbox-line {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  color: var(--muted);
  font-size: 0.86rem;
  font-weight: 700;
}

.switch-line input,
.checkbox-line input {
  width: 17px;
  height: 17px;
  accent-color: var(--accent);
}
```

- [ ] **Step 5: Remove obsolete classes**

After completing Tasks 4, 5, and 6, run:

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox/apps/web && bun run lint
```

Then delete any CSS classes from `styles.css` that are no longer referenced. Do NOT delete classes until all JSX refactor tasks are complete.

- [ ] **Step 6: Commit**

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox
git add apps/web/src/styles.css
git commit -m "feat(web): add Indigo Studio Sidebar design tokens and layout"
```

---

## Task 4: Refactor App Layout and Sidebar

**Files:**
- Modify: `apps/web/src/App.tsx`

**Interfaces:**
- Consumes: `useProviderCatalog`, provider/voice/model state, existing submit handlers.
- Produces: New top-level layout components using the CSS classes from Task 3.

- [ ] **Step 1: Extract the sidebar navigation component**

At the bottom of `apps/web/src/App.tsx`, add:

```typescript
const TTS_MODES: { id: TtsMode; label: string; icon: string }[] = [
  { id: "builtin", label: "Built-in", icon: "🔊" },
  { id: "design", label: "Design", icon: "✨" },
  { id: "clone", label: "Clone", icon: "🎙️" },
];

function Sidebar({
  activeMode,
  onModeChange,
  tab,
  onTabChange,
  supportsCapability,
}: {
  activeMode: TtsMode;
  onModeChange: (mode: TtsMode) => void;
  tab: MainTab;
  onTabChange: (tab: MainTab) => void;
  supportsCapability: (capability: string) => boolean;
}) {
  return (
    <nav className="sidebar" aria-label="Toolbox sections">
      <div>
        <div className="sidebar-section">TTS</div>
        {TTS_MODES.map((mode) => {
          const supported = supportsCapability(ttsCapability(mode.id));
          return (
            <button
              key={mode.id}
              className={["nav-item", activeMode === mode.id && tab === "tts" ? "active" : ""]
                .filter(Boolean)
                .join(" ")}
              type="button"
              disabled={!supported}
              onClick={() => {
                onModeChange(mode.id);
                onTabChange("tts");
              }}
            >
              <span>{mode.icon}</span>
              <span>{mode.label}</span>
            </button>
          );
        })}
      </div>
      <div>
        <div className="sidebar-section">ASR</div>
        <button
          className={["nav-item", tab === "asr" ? "active" : ""].filter(Boolean).join(" ")}
          type="button"
          disabled={!supportsCapability("asr.transcribe")}
          onClick={() => onTabChange("asr")}
        >
          <span>📝</span>
          <span>Transcribe</span>
        </button>
      </div>
    </nav>
  );
}
```

- [ ] **Step 2: Refactor the main return block**

Replace the outer `<main className="app-shell">` content in `App.tsx` so the top-level structure becomes:

```tsx
<main className="app-shell">
  <header className="topbar">
    <div className="brand">
      <div className="brand-mark">V</div>
      <div>
        <h1 className="brand-title">Voice Toolbox</h1>
        <p className="brand-subtitle">TTS / ASR provider workbench</p>
      </div>
    </div>
    <div className="provider-strip" aria-live="polite">
      <label>
        <select
          className="select-input"
          aria-label="Provider"
          value={selectedProviderId}
          onChange={(event) => setSelectedProviderId(event.target.value)}
        >
          {providers.length === 0 ? <option value="">No providers</option> : null}
          {providers.map((provider) => (
            <option key={provider.id} value={provider.id}>
              {provider.name}
            </option>
          ))}
        </select>
      </label>
      <KeyStatus provider={selectedProvider} loading={providersLoading} />
    </div>
  </header>

  <ProviderDetails provider={selectedProvider} />

  {globalError ? <div className="notice error">{globalError}</div> : null}

  <div className="workspace">
    <Sidebar
      activeMode={ttsMode}
      onModeChange={setTtsMode}
      tab={tab}
      onTabChange={setTab}
      supportsCapability={supportsCapability}
    />

    {tab === "tts" ? (
      <div className="canvas">
        {/* existing TTS form markup */}
      </div>
    ) : (
      <div className="canvas">
        {/* existing ASR form markup */}
      </div>
    )}

    <div className="output-panel">
      {tab === "tts" ? (
        <ResultPanel artifact={ttsArtifact} state={ttsState} />
      ) : (
        <TranscriptPanel artifact={asrArtifact} transcript={transcript} state={asrState} />
      )}
    </div>
  </div>
</main>
```

Remove the following old elements as part of this refactor:
- The `<nav className="tabs">` segmented TTS/ASR tabs.
- The `<section className="tool-grid">` wrappers around the TTS and ASR forms.
- The `<fieldset className="segmented" aria-label="TTS mode">` inside the TTS form (mode selection now lives in the sidebar).
- Any old conditional rendering of `ResultPanel` / `TranscriptPanel` outside the new `.output-panel` column.

Keep all existing state/hooks intact; only the markup structure and class names change in this step.

- [ ] **Step 3: Update helper components to new CSS classes**

In `apps/web/src/App.tsx`, update `KeyStatus`, `StatusItem`, and `ModelSummary` to use the new classes:

```tsx
function KeyStatus({ provider, loading }: { provider: Provider | null; loading: boolean }) {
  if (loading) {
    return <span className="status-badge">Key status loading</span>;
  }
  if (!provider || provider.has_api_key === undefined) {
    return <span className="status-badge">Key status unavailable</span>;
  }
  if (provider.has_api_key) {
    return <span className="status-badge ok">API key configured</span>;
  }
  return <span className="status-badge warn">API key missing</span>;
}

function StatusItem({ label, value }: { label: string; value: string }) {
  return (
    <span className="status-item">
      <span className="label">{label}</span>
      <strong>{value}</strong>
    </span>
  );
}

function ModelSummary({ models, selectedModel }: { models: ProviderModel[]; selectedModel: string | null }) {
  const model = models.find((item) => item.id === selectedModel);
  if (!model) {
    return (
      <span className="meta-label">
        <span>Model</span>
        <span>None</span>
      </span>
    );
  }
  return (
    <span className="meta-label">
      <span>Model</span>
      <span>{model.name || model.id}</span>
    </span>
  );
}
```

Also add a disabled style for sidebar nav items in `apps/web/src/styles.css`:

```css
.nav-item:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

- [ ] **Step 4: Commit intermediate layout refactor**

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox
git add apps/web/src/App.tsx apps/web/src/styles.css
git commit -m "feat(web): add Indigo Studio Sidebar layout and navigation"
```

---

## Task 5: Refactor Form Cards and Button Hierarchy

**Files:**
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/components/FullscreenTextEditor.tsx`

**Interfaces:**
- Consumes: Existing control props (`BuiltinControls`, `DesignControls`, `CloneControls`, `TextTools`, `AdvancedSettings`).
- Produces: Card-wrapped forms with unified buttons and consistent text editor actions.

- [ ] **Step 1: Update imports and FullscreenTextEditor**

In `apps/web/src/App.tsx`, add `ReactNode` and `useCallback` to the React import:

```typescript
import {
  FormEvent,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
} from "react";
```

In `apps/web/src/components/FullscreenTextEditor.tsx`, remove the `buttonLabel` prop and update the trigger and modal buttons:

```tsx
type FullscreenTextEditorProps = {
  title: string;
  value: string;
  onApply(value: string): void;
};

export function FullscreenTextEditor({ title, value, onApply }: FullscreenTextEditorProps) {
  ...
  return (
    <>
      <button
        className="expand-link"
        type="button"
        onClick={() => setOpen(true)}
        title="Expand"
        aria-label="Expand editor"
      >
        ↗
      </button>
      {open ? (
        <div className="modal-overlay" role="presentation">
          <section className="fullscreen-editor" role="dialog" aria-modal="true" aria-labelledby="fullscreen-title">
            <header className="fullscreen-editor__header">
              <h2 id="fullscreen-title">{title}</h2>
              <button className="btn btn-secondary" type="button" onClick={() => setOpen(false)}>
                Cancel
              </button>
            </header>
            <textarea
              className="fullscreen-editor__textarea script-input"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleEditorKeyDown}
              autoFocus
            />
            <footer className="fullscreen-editor__footer">
              <span>{draft.length} chars</span>
              <button className="btn btn-primary" type="button" onClick={apply}>
                Apply
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}
```

- [ ] **Step 2: Replace section heading actions**

In `App.tsx`, replace the `TextEditorActions` component with a simpler inline pattern inside each card header:

```tsx
function CardHeader({
  label,
  count,
  optional,
  title,
  value,
  onApply,
  extra,
}: {
  label: string;
  count?: number;
  optional?: boolean;
  title: string;
  value: string;
  onApply: (value: string) => void;
  extra?: ReactNode;
}) {
  return (
    <div className="card-header">
      <span className="card-label">{label}</span>
      <div className="card-actions">
        {extra}
        {optional ? (
          <span className="char-count">Optional</span>
        ) : count !== undefined ? (
          <span className="char-count">{count} chars</span>
        ) : null}
        <FullscreenTextEditor title={title} value={value} onApply={onApply} />
      </div>
    </div>
  );
}
```

Then remove the old `TextEditorActions` function.

- [ ] **Step 3: Wrap form sections in cards**

Refactor `BuiltinControls`, `DesignControls`, and `CloneControls` to return `<div className="card">` wrappers with `CardHeader` headers and `.text-input` / `.script-input` fields. Replace tag buttons with `.chip` and the custom tag input with `.tag-input`.

Use the `CardHeader` component defined in Step 2 for every card. For example, in `BuiltinControls`:

```tsx
<>
  <div className="card">
    <CardHeader label="Script" count={text.length} title="Script" value={text} onApply={setText} />
    <textarea
      className="script-input"
      ref={textAreaRef}
      value={text}
      rows={6}
      onChange={(event) => setText(event.target.value)}
      required
    />
    <div className="tag-row">
      {INLINE_TAGS.map((tag) => (
        <button key={tag} className="chip" type="button" onClick={() => insertTag(tag)}>
          {tag}
        </button>
      ))}
      <input
        className="tag-input"
        value={customTag}
        onChange={(event) => setCustomTag(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            submitCustomTag();
          }
        }}
        placeholder="+ tag"
      />
    </div>
  </div>

  <div className="card">
    <CardHeader label="Voice" title="Voice" value={voiceId} onApply={setVoiceId} />
    {/* keep the existing voice selector and style input */}
  </div>

  <div className="card">
    <AdvancedSettings
      label="Advanced"
      models={providerModels("tts.builtin")}
      selectedModel={builtinModel}
      onModelChange={setBuiltinModel}
    />
  </div>
</>
```

Apply the same pattern to `DesignControls` (cards for Voice description and Script/Preview) and `CloneControls` (cards for Reference audio, Script, and Style). Preserve all existing fields and logic; only change wrappers, headers, and button/input classes.

- [ ] **Step 4: Wrap TextTools in a card and restyle the Preview button**

Refactor `TextTools` so the format select and Preview button live inside a `.card`:

```tsx
<section className="card">
  <div className="card-header">
    <span className="card-label">Text format</span>
    <div className="card-actions">
      <select
        className="select-input"
        value={textFormat}
        onChange={(event) => setTextFormat(event.target.value as TextFormat)}
      >
        <option value="plain">plain</option>
        <option value="markdown">markdown</option>
        <option value="auto">auto</option>
      </select>
      <button
        className="btn btn-primary"
        type="button"
        onClick={onPreview}
        disabled={previewState === "loading"}
      >
        {previewState === "loading" ? "Previewing..." : "Preview"}
      </button>
    </div>
  </div>
  {previewError ? <div className="notice error compact">{previewError}</div> : null}
  {cleanedPreview ? <pre className="cleaned-preview">{cleanedPreview}</pre> : null}
</section>
```

- [ ] **Step 5: Update submit buttons to `.primary-action`**

Ensure the TTS and ASR submit buttons use `className="primary-action"`.

- [ ] **Step 6: Style AdvancedSettings and FullscreenTextEditor modal**

In `apps/web/src/App.tsx`, wrap each `<AdvancedSettings>` usage in a `.card`:

```tsx
<div className="card">
  <AdvancedSettings
    label="Advanced"
    models={providerModels("tts.builtin")}
    selectedModel={builtinModel}
    onModelChange={setBuiltinModel}
  />
</div>
```

In `apps/web/src/components/AdvancedSettings.tsx`, add a wrapper class:

```tsx
<details className="advanced-settings">
  <summary className="card-label">{label}</summary>
  <label className="field">
    <span className="field-title">Model</span>
    <select
      value={selectedModel ?? ""}
      onChange={(event) => onModelChange(event.target.value)}
      disabled={disabled || !hasModels}
    >
      {hasModels ? null : <option value="">No compatible models</option>}
      {models.map((model) => (
        <option key={model.id} value={model.id}>
          {model.name || model.id}
        </option>
      ))}
    </select>
  </label>
</details>
```

In `apps/web/src/styles.css`, add or replace the `.advanced-settings` rule:

```css
.advanced-settings {
  border: 0;
  padding: 0;
}

.advanced-settings summary {
  list-style: none;
  cursor: pointer;
}

.advanced-settings summary::-webkit-details-marker {
  display: none;
}

.advanced-settings .field {
  margin-top: 12px;
}
```

- [ ] **Step 7: Commit**

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox
git add apps/web/src/App.tsx apps/web/src/components/FullscreenTextEditor.tsx
git commit -m "feat(web): refactor form cards, buttons, and editor actions"
```

---

## Task 6: Output Panel and History Integration

**Files:**
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/api.ts` (already updated in Task 2)

**Interfaces:**
- Consumes: `getArtifacts`, `Artifact`, current artifact state.
- Produces: `HistoryPanel` component rendered below `ResultPanel` / `TranscriptPanel`.

- [ ] **Step 1: Add a HistoryPanel component**

At the bottom of `apps/web/src/App.tsx`, add:

```typescript
function HistoryPanel({
  artifacts,
  onSelect,
}: {
  artifacts: Artifact[];
  onSelect: (artifact: Artifact) => void;
}) {
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">History</span>
        <span className="char-count">last {artifacts.length}</span>
      </div>
      <div className="history-list">
        {artifacts.length === 0 ? (
          <p className="char-count">No history yet.</p>
        ) : (
          artifacts.map((artifact) => (
            <div key={artifact.id} className="history-item">
              <div className="history-meta">
                <span className="history-title">{formatHistoryTitle(artifact)}</span>
                <span className="history-time">{formatHistoryTime(artifact.created_at)}</span>
              </div>
              <button
                className="btn btn-ghost"
                type="button"
                aria-label={`Load ${formatHistoryTitle(artifact)}`}
                onClick={() => onSelect(artifact)}
              >
                {artifact.kind === "audio" ? "Play" : "View"}
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function formatHistoryTitle(artifact: Artifact): string {
  const op = artifact.operation ?? "unknown";
  const kind = artifact.kind ?? "unknown";
  if (op === "tts" && kind === "audio") {
    const mode = String(artifact.metadata?.tts_mode ?? "unknown");
    const label =
      mode === "builtin"
        ? "Built-in"
        : mode === "design"
          ? "Design"
          : mode === "clone"
            ? "Clone"
            : mode;
    return `TTS • ${label}`;
  }
  if (op === "asr" || kind === "transcript") return "ASR • Transcribe";
  return `${op} • ${kind}`;
}

function formatHistoryTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}
```

- [ ] **Step 2: Update imports in App.tsx**

In `apps/web/src/App.tsx`, add `getArtifacts` to the `./api` import:

```typescript
import {
  Artifact,
  Provider,
  ProviderModel,
  TextFormat,
  Voice,
  cloneVoice,
  designVoice,
  getArtifacts,
  getVoices,
  normalizeText,
  synthesizeBuiltin,
  transcribe,
} from "./api";
```

- [ ] **Step 3: Load history in App and pass it to the output column**

In the `App` component, add:

```typescript
const [history, setHistory] = useState<Artifact[]>([]);
const [historyError, setHistoryError] = useState("");
const historyMountedRef = useRef(true);

useEffect(() => {
  historyMountedRef.current = true;
  return () => {
    historyMountedRef.current = false;
  };
}, []);

// useCallback with empty deps so the initial load effect and the post-submit
// refresh share one stable identity and exhaustive-deps stays satisfied.
const refreshHistory = useCallback(() => {
  return getArtifacts(20)
    .then((items) => {
      if (!historyMountedRef.current) return;
      setHistory(items);
      setHistoryError("");
    })
    .catch((err) => {
      if (!historyMountedRef.current) return;
      setHistoryError(err instanceof Error ? err.message : "Failed to load history");
    });
}, []);

useEffect(() => {
  void refreshHistory();
}, [refreshHistory]);
```

Add `useCallback` to the existing React import in `App.tsx` (it already imports `useEffect`, `useRef`, `useState`).

Call `refreshHistory()` after successful TTS/ASR submissions. In the TTS submit handler, insert it after `setTtsState("success")`:

```typescript
      setTtsArtifact(result.artifact);
      setTtsState("success");
      void refreshHistory();
```

In the ASR submit handler, insert it after `setAsrState("success")`:

```typescript
      setTranscript(await transcriptResponse.text());
      setAsrState("success");
      void refreshHistory();
```

- [ ] **Step 4: Add a history selection handler that branches by artifact kind**

In the `App` component, add:

```typescript
async function selectHistoryItem(artifact: Artifact) {
  setTtsError("");
  setAsrError("");
  if (artifact.kind === "audio") {
    setTtsArtifact(artifact);
    setTtsState("success");
    setTab("tts");
    return;
  }
  setAsrArtifact(artifact);
  setTranscript("");
  setAsrState("loading");
  setTab("asr");
  try {
    // Plain fetch, not requestJson: the download endpoint returns the raw
    // transcript as text/plain, not JSON. requestJson expects a JSON body and
    // would throw on the non-JSON response.
    const response = await fetch(artifact.download_url);
    if (!response.ok) {
      throw new Error(`Transcript download failed with status ${response.status}`);
    }
    setTranscript(await response.text());
    setAsrState("success");
  } catch (err) {
    setTranscript("");
    setAsrError(err instanceof Error ? err.message : "Failed to load transcript");
    setAsrState("error");
  }
}
```

- [ ] **Step 5: Render history below the output panel**

In the right-hand output column, render:

```tsx
<div className="output-panel">
  {historyError ? <div className="notice error compact">{historyError}</div> : null}
  {tab === "tts" ? (
    <ResultPanel artifact={ttsArtifact} state={ttsState} />
  ) : (
    <TranscriptPanel artifact={asrArtifact} transcript={transcript} state={asrState} />
  )}
  <div role="status" aria-live="polite" className="sr-only">
    {history.length} history items
  </div>
  <HistoryPanel artifacts={history} onSelect={selectHistoryItem} />
</div>
```

Add a screen-reader-only helper to `styles.css`:

```css
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
```

- [ ] **Step 6: Constrain output panel height for long history lists**

In `apps/web/src/styles.css`, update `.output-panel` so it does not grow taller than the viewport:

```css
.output-panel {
  position: sticky;
  top: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: calc(100vh - 40px);
  overflow-y: auto;
}
```

- [ ] **Step 7: Commit**

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox
git add apps/web/src/App.tsx apps/web/src/styles.css
git commit -m "feat(web): add history panel and wire to backend"
```

---

## Task 7: Verify Build, Tests, and Manual Checks

**Files:**
- All modified files.

**Interfaces:**
- Consumes: Complete implementation from Tasks 1–6.
- Produces: Passing test/build results.

- [ ] **Step 1: Run backend lint and tests**

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox
uv run ruff check apps/api/src/voice_toolbox_api tests/test_api.py
uv run ruff format --check apps/api/src/voice_toolbox_api tests/test_api.py
uv run pytest tests/test_api.py -v
uv run pytest -v
```

Expected: No lint/format errors; all API tests pass, including `test_list_artifacts`. The full suite is run because Task 1 Step 5 modifies `_run_tts`, which may affect provider/audio-conversion tests.

- [ ] **Step 2: Run frontend lint, typecheck, and tests**

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox/apps/web
bun run lint
bun run format:check
bun run test
```

Expected: `tsc --noEmit` and `vitest run` pass.

- [ ] **Step 3: Build frontend for production**

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox/apps/web && bun run build
```

Expected: Build succeeds with no errors.

- [ ] **Step 4: Manual smoke checks**

Start the API and web dev server:

```bash
# Terminal 1
cd /Users/dengqi/Source/langs/python/voice-toolbox && uv run voice-toolbox server

# Terminal 2
cd /Users/dengqi/Source/langs/python/voice-toolbox/apps/web && bun run dev
```

Then visit `http://127.0.0.1:5173/` and verify:

- The Indigo Studio Sidebar layout renders.
- Provider switching updates the sidebar and available models.
- TTS built-in/design/clone modes switch correctly.
- ASR mode renders the upload form.
- Generate voice / Transcribe produce output in the right panel.
- The fullscreen editor opens from the script card and applies text correctly.
- Audio tag chips insert tags; custom tags submit on Enter.
- The History panel lists recent artifacts after generation.
- Clicking a history item loads it into the Output card.
- Responsive breakpoints collapse gracefully at 1024px and 819px.

- [ ] **Step 5: Final commit**

```bash
cd /Users/dengqi/Source/langs/python/voice-toolbox
git add -A
git commit -m "feat(web): complete Indigo Studio Sidebar redesign with history panel"
```

---

## Spec Coverage Check

| Spec Section | Implementing Task |
|--------------|-------------------|
| Indigo color tokens | Task 3 |
| Studio Sidebar layout | Tasks 3, 4 |
| Header + provider strip | Task 4 |
| Card-wrapped forms | Tasks 3, 5 |
| Button hierarchy | Tasks 3, 5 |
| Unified text editor actions | Task 5 |
| Audio tags as chips | Task 5 |
| Output panel | Tasks 3, 6 |
| History panel | Tasks 1, 2, 6 |
| `GET /v1/artifacts` endpoint | Task 1 |
| Responsive behavior | Task 3 |

## Placeholder Scan

- No "TBD", "TODO", or "implement later" strings remain.
- Every task includes exact file paths and concrete code or commands.
- History metadata scope is explicitly limited to sidecar fields.

## Type Consistency Check

- `Artifact` type is reused from `apps/web/src/api.ts`; no new fields are invented.
- `GET /v1/artifacts` returns the same `_safe_artifact_payload` shape used by existing artifact endpoints.
- `TtsMode` and `MainTab` types already exist in `App.tsx` and are used by the new `Sidebar` component.
