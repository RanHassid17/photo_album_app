# Photo Album Creator — Architectural Design Document

**Status:** Draft v1.0
**Author:** Architecture pass from `prompt_creator/Photo_Album_Creator_Prompt_Spec.md`
**Date:** 2026-05-26
**Audience:** Engineering team, future contributors, stakeholder review

This document is the response to the architectural questions posed in `prompt_creator/claude_first_prompt_photo_album_creator.md`. It is opinionated, optimized for fast MVP delivery on a single local machine, and designed so the same seams scale to a commercial SaaS without rewrites.

---

## 1. Executive Summary

**Photo Album Creator** is a privacy-first web application that turns a user's scattered personal photo libraries (Google Photos, iCloud, WhatsApp exports, local folders) into a finished photo album — digital flipbook and/or print-ready files — in under 30 minutes.

The product's competitive bet is **AI-assisted curation, not AI-imposed curation**. Claude Sonnet 4.6 orchestrates specialist agents (vision indexing, photo selection, album layout). Open-source vision models (DeepFace, YOLOv8) handle the per-photo work locally so user photos never need to leave the user's account. The user can override every AI decision at any step.

**Why this exists:** Existing tools (Google Photos memories, iPhone "for you" albums) are passive and locked to one ecosystem. Print-shop tools (Shutterfly, MyMemories) require hours of manual drag-and-drop. The gap is an AI tool that ingests *across* sources, designs intelligently, and exports for both screen and print — with full user control.

**MVP scope (this document):** Local folder source only, open-source vision stack, local dev environment (Docker Compose for Postgres + Redis; backend/frontend run natively). All cross-source plumbing and cloud vision providers are designed as interfaces so V1 adds them without refactor.

**Primary KPIs:** Time-to-first-album <30 min · Filter latency <5s at 5K photos · Layout accepted as-is in ≥60% of sessions · Print exports DPI-compliant 100% of the time.

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              Browser (he/en RTL)                         │
│   ┌───────────────────────────────────────────────────────────────────┐  │
│   │  React + TypeScript + Vite + Tailwind + i18next + react-query    │  │
│   │  Wizard:  Connect → Filter → Select → Design → Export             │  │
│   │  Canvas editor (Fabric.js) for manual layout override             │  │
│   └───────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │ HTTPS (REST + SSE for job progress)
                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         FastAPI Backend (Python 3.12)                    │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐         │
│  │ /sources   │  │ /photos    │  │ /selection │  │ /layouts   │         │
│  │ /jobs      │  │  search    │  │ /albums    │  │ /export    │         │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘         │
│        │               │               │               │                 │
│        ▼               ▼               ▼               ▼                 │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │           Domain services (sources/, agents/, exporters/)         │  │
│  │  PhotoSource iface  │  VisionProvider iface  │  AgentPrompts      │  │
│  └─────┬─────────────────────┬─────────────────────────┬─────────────┘  │
│        │                     │                         │                 │
└────────┼─────────────────────┼─────────────────────────┼─────────────────┘
         │                     │                         │
         ▼                     ▼                         ▼
   ┌──────────┐         ┌──────────────┐          ┌──────────────────┐
   │ Postgres │         │ Celery queue │          │ Anthropic API    │
   │ (metadata│         │   (Redis)    │          │ Claude Sonnet 4.6│
   │  + face  │         └──────┬───────┘          │ (selection +     │
   │  cluster │                ▼                  │  layout agents)  │
   │  + album)│         ┌──────────────┐          └──────────────────┘
   └──────────┘         │ Vision worker│
                        │ DeepFace     │
                        │ YOLOv8       │
                        │ Pillow/EXIF  │
                        └──────┬───────┘
                               ▼
                      ┌──────────────────┐
                      │  Local FS        │
                      │  PHOTO_STORAGE   │
                      │  (originals +    │
                      │   thumbnails)    │
                      └──────────────────┘
```

**Key flows:**

- **Ingest** — frontend uploads/points at a folder → API copies/hashes/dedupes into storage → enqueues `index_photo` jobs → worker fills face/label/EXIF tables → frontend polls `/jobs/{id}` for progress.
- **Filter** — frontend posts filter criteria → API runs a single indexed Postgres query → returns paginated photo metadata + thumbnail URLs.
- **AI selection** — backend assembles a metadata-only JSON payload (no image bytes), calls Claude with the Selection Agent system prompt, returns ranked photo IDs with human-readable reasoning.
- **AI layout** — backend calls Claude with tool-use; response is a strict layout JSON validated against a Pydantic schema; deterministic grid fallback if validation fails.
- **Export** — Playwright (Python) renders each album page to PDF for digital; Pillow re-encodes originals at 300 DPI per print size into a ZIP for print.

---

## 3. Core Services / Modules

Spec §14 names five agents. Mapped to code modules:

| Spec Agent | Module | Tech | MVP scope |
|---|---|---|---|
| 1. Source Connection | `backend/app/sources/` | Python iface + per-source impls | `LocalFolderSource` only |
| 2. Photo Vision (indexing & filtering) | `backend/app/workers/vision.py`, `backend/app/services/filter.py` | Celery worker; SQL filter | DeepFace + YOLOv8 + EXIF |
| 3. Album Designer | `backend/app/agents/layout.py` | Claude Sonnet 4.6 tool-use | JSON layout + deterministic fallback |
| 4. UX/UI | `frontend/src/features/` | React + Vite + Tailwind | Full wizard |
| 5. Print Export | `backend/app/exporters/print.py`, `exporters/digital.py` | Pillow + Playwright | 10×15, 13×18, 20×30 cm + PDF |

Additional cross-cutting modules:

- `backend/app/agents/selection.py` — Selection Agent (Claude call returning ranked photo IDs).
- `backend/app/agents/prompts.py` — single source of truth for all agent system prompts (kept out of business logic so they can be revised without code review of the call sites).
- `backend/app/models/` — SQLAlchemy ORM models.
- `backend/app/api/` — FastAPI routers, one per resource.
- `backend/app/jobs/` — Celery task definitions + job-status table.

---

## 4. Database & Storage Strategy

### Why Postgres (not Mongo / SQLite)

The data is fundamentally relational: photos → face_embeddings → face_clusters (many-to-many), photos → labels (many-to-many), albums → pages → items → photos. Postgres also gives us strong indexes for the filter latency goal (<5s on 5K photos) and a clean V1 upgrade path to `pgvector` for face-similarity search.

SQLite would work for true single-user MVP but locks us out of concurrent worker writes during indexing.

### Schema (MVP tables)

```sql
photos            (id, source, source_ref, sha256 UNIQUE, original_path,
                   stored_path, taken_at, gps_lat, gps_lng, width, height,
                   blur_score, indexed_at, created_at)
face_embeddings   (id, photo_id FK, bbox JSONB, embedding BYTEA,
                   cluster_id FK NULL)
face_clusters     (id, name NULL, representative_photo_id FK, created_at)
photo_labels      (id, photo_id FK, label, confidence)     -- "dog","cat",…
albums            (id, name, style, page_count, created_at)
album_pages       (id, album_id FK, index, layout_json JSONB)
album_items       (id, page_id FK, photo_id FK, position JSONB,
                   comment TEXT, comment_position)         -- above|below|left|right
jobs              (id, kind, status, progress, payload JSONB, error TEXT,
                   created_at, finished_at)
```

**Indexes:** `photos(taken_at)`, `photos(gps_lat, gps_lng)`, `photo_labels(label)`, `face_embeddings(cluster_id)`, `jobs(status, created_at)`.

### Blob storage

MVP: local filesystem at `$PHOTO_STORAGE_DIR/{user_id}/{photo_id}.{ext}` plus a sibling `_thumbs/{photo_id}.webp` for grid display. Thumbnails are generated during indexing (max 512px long edge, WebP, quality 80).

V1 upgrade: swap to S3-compatible (MinIO local, S3 cloud) behind a `BlobStore` interface in `backend/app/storage/`. The interface is defined now even though only one impl exists, so the API code never hardcodes paths.

### Face embeddings storage

MVP stores 128-d float32 embeddings as `BYTEA` and clusters in-process with HDBSCAN once per ingest batch. V1 switches to `pgvector` for incremental nearest-neighbor queries when a new photo arrives.

---

## 5. AI Agent Orchestration Design

### Principle: Claude as a *specialist consultant*, not an autopilot

Each call to Claude is short, targeted, and bounded:
- Inputs are metadata JSON (never raw image bytes — bytes stay in workers).
- Outputs are validated against Pydantic schemas; failed validation triggers a deterministic fallback, not a retry storm.
- The orchestration code (Python) decides the *order* of calls; Claude decides the *content* within each call.

### Agents

**Selection Agent (`agents/selection.py`)**
- **Input:** array of `{id, taken_at, persons[], labels[], blur_score, caption}` + criteria + target count.
- **Prompt:** spec §9 persona ("warm creative album designer"), explicit anti-duplication rules, scoring rubric.
- **Output:** `[{photo_id, score, reason}]` — Pydantic-validated.
- **Fallback:** deterministic ranker (blur_score weighted by date diversity).

**Layout Agent (`agents/layout.py`)**
- **Input:** photo list + page count + style + aspect ratios.
- **Prompt:** spec §9 + golden-ratio rules + style hints.
- **Tool-use:** single `submit_layout` tool with strict JSON schema for `pages[].grid` and `pages[].items[]`.
- **Output:** `LayoutPlan` model — validated.
- **Fallback:** deterministic 2×2 / 3×2 grid generator.

### Why no multi-step "agentic loops" in MVP

Spec asks for assistive AI, not autonomous AI. Multi-step Claude loops would inflate latency and cost without observable user benefit. If V1 introduces "iterate on layout until user approves," it should be a single tool-use turn driven from a frontend feedback button, not an autonomous loop.

### Cost & latency controls

- Pass photo IDs and metadata only — never base64 images. Spec §5 says max ~32K input tokens, well within budget for 500-photo album metadata.
- Cache layout suggestions keyed on `(photo_ids hash, page_count, style)` — re-renders shouldn't re-call Claude.
- Use Claude **Sonnet** 4.6 as default, not Opus. Selection and layout are well-bounded tool-use tasks where Sonnet's quality is sufficient and latency is ~3× faster.

---

## 6. Frontend Architecture

**Stack:** React 18 + TypeScript + Vite + Tailwind + react-router + @tanstack/react-query + zustand + react-i18next + Fabric.js + react-pageflip + vitest.

### Why these choices

- **Vite over Next.js** — MVP is a SPA, not SSR. Vite is faster for local dev and there's no SEO need (this is a tool, not content).
- **Tailwind** — RTL-friendly with logical properties (`ps-`, `pe-`, `ms-`, `me-`); no custom CSS layer needed for the wizard.
- **react-query for server state, zustand for client state** — clear split between "what the server says" and "what the user is doing right now."
- **Fabric.js for the canvas editor** — battle-tested for drag-resize-rotate. Konva is also fine; Fabric chosen for marginally better text handling (important for Hebrew captions inside canvas).
- **react-pageflip** for the Lupa-style digital flipbook.

### Feature folders (vertical slices)

```
frontend/src/features/
  ingest/         FolderPicker, UploadProgress, IngestJobPoller
  filter/         FilterPanel, FaceClusterChips, DateRange, LabelChips
  selection/      MasonryGrid, PhotoCard, SelectionToolbar, AIBadge
  album_editor/   AlbumCanvas, PageThumbnails, CommentEditor, StylePicker
  export/         ExportDialog, PrintSizePicker, DownloadButton
```

### RTL strategy

- `i18next` initialized with `he` as default, falls back to `en`.
- `<html dir>` toggled by the i18n hook.
- **No hardcoded `left/right` Tailwind classes** — only logical (`ps-4`, not `pl-4`). Lint rule via ESLint custom rule (added in Phase B.7).
- Fabric.js canvas captions use explicit `textBaseline` + `direction: 'rtl'` properties; verified manually because Fabric's auto-detection is unreliable.

### State

- Wizard step: `useSearchParams` (`?step=filter`) — survives reload, shareable URL.
- Selection set: zustand store (`useSelection()`), persisted to `sessionStorage`.
- Album draft: react-query mutation against `/api/albums/{id}` — server is source of truth, optimistic updates on the client.

---

## 7. Backend Architecture

**Stack:** Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic + Pydantic v2 + Celery + Redis + pytest + httpx (test client).

### Why FastAPI (not Django, not Flask)

- Async-native — long-running uploads and SSE job-status streams are first-class.
- Pydantic v2 schemas double as request/response models and as validation for Claude tool-use output.
- Auto-generated OpenAPI schema → frontend can codegen a typed client (`openapi-typescript-codegen`) so API contracts can't drift.
- FastAPI is widely understood; no framework lock-in surprises.

### Layered structure

```
backend/app/
  api/            # FastAPI routers — thin, only HTTP concerns
  services/       # business logic — depends only on models + sources/agents
  agents/         # Claude calls (selection.py, layout.py, prompts.py)
  sources/        # PhotoSource interface + impls
  workers/        # Celery tasks (vision.py, indexing.py)
  exporters/      # print.py, digital.py
  storage/        # BlobStore interface + LocalBlobStore impl
  models/         # SQLAlchemy ORM
  schemas/        # Pydantic request/response models
  db.py, config.py, main.py
```

**Rule:** `api/` calls `services/`; `services/` calls `agents/`, `sources/`, `models/`. No layer skipping. This keeps Claude/vision code testable without spinning up HTTP.

### Async job model

- `POST /api/sources/local-folder` returns immediately with a `job_id`.
- Celery worker processes ingest + vision in batches; updates `jobs.progress` (0-100).
- Frontend polls `GET /api/jobs/{job_id}` every 2s. V1 upgrade: switch to SSE (`/api/jobs/{job_id}/stream`) when polling becomes wasteful.

### Auth (deferred to V1)

MVP runs locally for a single user. There's an implicit `user_id = "local"`. Auth is wired as a FastAPI dependency stub (`get_current_user`) that returns the local user — V1 swaps this to a real provider (Auth0 / Clerk / Supabase) without touching call sites.

### Secrets

`.env` (gitignored) loaded via `pydantic-settings`. `.env.example` checked in. **No OAuth in MVP** — that secret-handling cost arrives with V1.

---

## 8. Folder Structure

```
photo_album_app/
├── docs/
│   ├── ARCHITECTURE.md           # this file
│   └── (more docs as we go)
├── prompt_creator/               # existing spec files
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── api/
│   │   │   ├── sources.py jobs.py photos.py selection.py
│   │   │   ├── layouts.py albums.py export.py
│   │   ├── services/
│   │   ├── agents/  (selection.py layout.py prompts.py)
│   │   ├── sources/ (base.py local_folder.py)
│   │   ├── workers/ (vision.py celery_app.py)
│   │   ├── exporters/ (print.py digital.py)
│   │   ├── storage/ (base.py local.py)
│   │   ├── models/  (photo.py face.py label.py album.py job.py)
│   │   └── schemas/
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx App.tsx routes.tsx
│       ├── features/  (ingest filter selection album_editor export)
│       ├── components/
│       ├── lib/  (api.ts queryClient.ts store.ts i18n.ts)
│       └── i18n/  (he.json en.json)
├── docker-compose.yml            # Postgres 16 + Redis 7
├── Makefile                      # dev, migrate, test, worker, lint
├── .env.example
├── .gitignore
└── README.md
```

---

## 9. External APIs & Services

### MVP — none paid

- **Anthropic API** (Claude Sonnet 4.6) — only paid dependency. Needed for selection and layout. User supplies `ANTHROPIC_API_KEY` in `.env`.
- **DeepFace** — pip package, runs locally.
- **Ultralytics YOLOv8n** — pip package, downloads weights on first use (~6 MB).
- **Pillow, exifread, OpenCV-headless** — pip packages.
- **Playwright (Python)** — pip + `playwright install chromium`. Used server-side for PDF rendering.

### V1 additions (designed for, not built)

| Service | Purpose | Interface seam |
|---|---|---|
| Google Photos API | Source connection | `PhotoSource` impl |
| iCloud Drive bridge or Apple Shortcuts webhook | Source connection | `PhotoSource` impl |
| AWS Rekognition (or replicate.com swap) | Higher-accuracy face clustering | `VisionProvider` impl |
| Google Geocoding / Nominatim | Reverse geocode GPS → place name | `Geocoder` iface |
| Cloudflare R2 / S3 | Blob storage in cloud | `BlobStore` impl |
| Stripe | Print-order checkout (V2+) | `Payments` module |
| Sentry | Error monitoring | wired in `main.py` |

The point: every V1 integration is a *new file implementing an existing interface*, not a rewrite.

---

## 10. Phased MVP Roadmap

Each phase is a vertical slice that ends with the app being runnable end-to-end at that level of capability.

### P0 — Scaffold (1 day)
- Monorepo + docker-compose + Makefile.
- Backend `/healthz` endpoint, frontend "Hello עברית" page with RTL toggle.
- Postgres + Redis come up via `docker compose up`.
- **Exit criterion:** `make dev` opens an RTL-correct page that hits the backend `/healthz`.

### P1 — Ingest + index (3-4 days)
- `LocalFolderSource` with ZIP upload + path-pointer modes.
- Photo dedup by SHA-256; EXIF extraction; thumbnail generation.
- Celery vision worker with DeepFace (face embed) + YOLOv8 (labels) + HDBSCAN clustering.
- Frontend ingest UI with live progress.
- **Exit criterion:** upload 50 mixed photos, see them in DB with faces clustered and labels populated.

### P2 — Filter + manual selection (2-3 days)
- `/api/photos/search` with all four filter dimensions.
- Frontend `FilterPanel` + masonry grid + click-to-select.
- Face clusters displayed as chips with the cluster's representative thumbnail; user can rename.
- **Exit criterion:** filter to "Maya in 2024" returns correct photos in <5s; manual selection persists across reload.

### P3 — AI selection + AI layout (3-4 days)
- Selection Agent: Claude call → ranked list with reasoning shown in UI.
- Layout Agent: tool-use → `AlbumPage[]` JSON → React renders grid → Fabric.js canvas allows drag/resize/rotate override.
- Comment block editor (above/below/left/right, max 200 chars, RTL-aware).
- **Exit criterion:** start from filtered set, get AI selection, get AI layout, drag one photo, add a Hebrew caption — all persisted.

### P4 — Export (2 days)
- Digital: Playwright renders pages → single PDF.
- Print: Pillow resizes per print size at 300 DPI → ZIP organized by size folder.
- Low-res warning surfaced in UI before export.
- **Exit criterion:** ZIP downloads with `/10x15/`, `/13x18/`, `/20x30/` folders, all 300 DPI; PDF opens correctly.

### P5 — Polish (1-2 days)
- E2E smoke test (Playwright Python) covering the whole flow.
- Empty/error states for every screen.
- Per-section README in `docs/`.
- **Exit criterion:** a fresh clone can run the full smoke test in CI.

**Total MVP estimate:** ~12-16 working days for a single experienced full-stack developer. Faster if pair-programming with Claude on routine pieces (i18n resource files, Pydantic schemas, exporters).

### V1 (post-MVP, not in this plan)
- Google Photos source + OAuth.
- Optional Rekognition vision provider.
- Reverse geocoding.
- Multi-user + cloud deploy.
- pgvector for face similarity search across albums.

---

## 11. Biggest Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Open-source face clustering accuracy** below spec's 90% precision target | High | High — undermines core "filter by person" UX | Tune HDBSCAN min_cluster_size; let user merge/split clusters in UI; document Rekognition swap path |
| **Vision indexing latency** at 5K photos on CPU (~1-3 hours) | High | Medium — user perceives the app as slow | Make indexing visibly async with per-photo progress; ship batched processing so a partial library is usable while the rest indexes |
| **Claude layout JSON quality** — non-spatial reasoning is unproven | Medium | High — bad layouts break the wow moment | Strict Pydantic schema + deterministic fallback that always produces *something* valid; show "AI suggestion" badge so user expectations are calibrated |
| **Hebrew RTL in canvas (Fabric.js)** edge cases | Medium | Medium — caption rendering may break | Manually test every text-on-canvas path; budget a half-day specifically for RTL canvas |
| **EXIF unreliability** across sources (WhatsApp strips most EXIF) | High (later phases) | Medium — date/location filters miss photos | MVP only handles local folder where EXIF is usually intact; for V1 WhatsApp source, parse filename patterns + chat-export metadata |
| **Anthropic API outages / rate limits** | Low | High during outage | Selection and layout both have deterministic fallbacks — app degrades gracefully to non-AI mode |
| **Disk space on user machine** (5K photos + thumbnails ≈ 20-40 GB) | Medium | Medium — silent failures on full disk | Pre-flight disk space check on ingest; fail loudly with clear message |
| **Privacy regression** (a future contributor accidentally sends photo bytes to Claude) | Low | Critical — violates core promise | Architectural rule enforced by code review: `agents/` modules MUST NOT import from `storage/` or accept `bytes`. Add a lint check |
| **Spec ambiguity: "iCloud bridge"** has no real implementation path | Medium | Medium for V1 (not MVP) | Flag now: shared-folder approach is fragile; Apple Shortcuts is per-user-setup. May force "no iCloud" in V1 |

### Spec issues flagged for the user (improvement suggestions)

- Spec §10.1 says "OAuth tokens stored server-side with encryption" but doesn't specify the encryption-at-rest mechanism. Recommend KMS-managed envelope encryption for V1.
- Spec §14 lists Canva/Adobe Express API as layout options — these are not free and add a third-party dependency for a core feature. Recommend dropping in favor of the custom grid + Claude approach.
- Spec promises "Lupa-style flipbook" — assuming this means a page-turn UI (react-pageflip / StPageFlip). Worth confirming visually with stakeholder before P3.
- Spec §13 sets "Layout approved without manual changes in ≥60% of sessions" as v1 target — measuring this requires telemetry (PostHog / Plausible). Not in MVP; flag for V1.

---

## 12. What to Build First

The next session starts here: **P0 monorepo scaffold**, executed by Phase B.0 of the approved plan.

Concretely, the very first PR:

1. `docker-compose.yml` with Postgres 16 + Redis 7 services.
2. `backend/pyproject.toml`, `backend/app/main.py` with `/healthz`, `backend/app/config.py`, `backend/app/db.py`, an Alembic init + first empty migration.
3. `frontend/` Vite + React + TS + Tailwind, with `App.tsx` rendering a Hebrew greeting that hits `/healthz` and shows the response.
4. `Makefile` with `make dev` (parallel uvicorn + vite), `make migrate`, `make worker`, `make test`.
5. `.env.example`, `.gitignore`, `README.md` with three-command quickstart.

Once `make dev` runs cleanly and the browser shows a working RTL page calling the backend, P1 (ingest + indexing) starts.

---

*— End of Architecture Document v1.0 —*
