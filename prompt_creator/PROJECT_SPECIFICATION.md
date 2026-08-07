# Final Project Specification — Photo Album Creator

**A privacy-first AI platform for turning scattered photo libraries into finished digital and print-ready albums**

Updated: 7 August 2026
Submitted as part of the final project in the AI Development certification programme, The Hebrew University of Jerusalem

---

## 1. Project Summary

**Photo Album Creator** is a web-based application, written in Hebrew with right-to-left (RTL) layout support, that turns a user's scattered personal photo libraries — Google Photos, iCloud, WhatsApp exports, local folders — into a finished photo album: a digital flipbook and/or print-ready files, in under 30 minutes.

The system combines **open-source computer vision** running locally (DeepFace for face recognition, YOLOv8 for object labelling, EXIF and blur analysis for quality scoring) with **Claude Sonnet 4.6** acting as a specialist curation and design consultant. Photos are ingested, indexed, filtered, intelligently selected, laid out across album pages, and exported as a multi-page PDF or a 300 DPI print-ready archive.

The product's competitive bet is **AI-assisted curation, not AI-imposed curation.** The user can override every AI decision at any step. This is a deliberate product stance: existing tools are either passive and ecosystem-locked (Google Photos memories, iPhone "For You" albums) or require hours of manual drag-and-drop (Shutterfly, MyMemories). The gap this project addresses is an AI tool that ingests *across* sources, designs intelligently, and exports for both screen and print — while leaving the human in control.

A second defining property is **privacy by architecture.** Raw image bytes never leave the user's environment to reach an external AI provider. The vision models run locally on the user's own photos; only derived metadata JSON — identifiers, timestamps, detected labels, quality scores — is ever sent to Claude. This is not a policy statement but an enforced constraint: the agent layer is structurally incapable of receiving image bytes.

The project is developed and maintained by the submitter as sole developer and sole product manager. The MVP is feature-complete across all six planned phases, and V1 work — managed cloud deployment — is planned and documented.

## 2. Project Goals

- Build an **AI system** that performs genuinely complex creative tasks — photo curation and page layout design — with validated, structured outputs rather than free text.
- Implement a full **Full-Stack architecture** comprising a typed React frontend, an async FastAPI backend, a relational database, a background job pipeline, and a computer-vision worker layer.
- Integrate **open-source computer vision** (face recognition, object detection, image quality analysis) as a working production pipeline, not a notebook demonstration.
- Demonstrate development with **AI tooling (Claude / Claude Code)** as an integral part of the engineering process, alongside a **Stitch / Figma MCP** design-to-code workflow.
- Manage a complete software product lifecycle: architectural design, phased delivery, testing, linting, containerised local infrastructure, and a documented deployment path.
- Deliver a genuinely **bilingual, RTL-first interface**, with correctness enforced by tooling rather than convention.
- Design every external dependency behind an **interface seam**, so that moving from local development to managed cloud services is an addition rather than a rewrite.

## 3. Target Users

- **End users — private individuals** who have accumulated large, disorganised photo libraries across several services and want a finished album without hours of manual work. Hebrew-speaking, RTL interface, desktop-first for the album editing workflow.
- **Users preparing albums for events and gifts** — weddings, family milestones, annual retrospectives — where print-quality output at 300 DPI is a hard requirement rather than a nice-to-have.
- **Privacy-conscious users** who are unwilling to upload an entire personal photo library to a third-party AI service. The local-vision architecture is aimed directly at this group.

## 4. Technology Architecture

The project is built on a **client–server architecture** with clear separation between the client layer, the API layer, the asynchronous worker layer, the AI agent layer and the data layer. Local development runs on Docker Compose; the V1 deployment target is Railway with Supabase as managed data infrastructure.

| Layer / Domain | Technologies in use |
|---|---|
| **Frontend** | **React 18 + TypeScript + Vite**, styled with **Tailwind CSS**, internationalised with **i18next** (Hebrew, RTL). Organised as vertical feature slices |
| **Backend** | **Python 3.12 + FastAPI** — async API layer with **Pydantic** validation and auto-generated OpenAPI; **SQLAlchemy 2.0** ORM with **Alembic** schema migrations |
| **Database** | **PostgreSQL 16**, chosen over MongoDB/SQLite for relational integrity across photos, albums, pages and detected persons |
| **Async jobs** | **Celery + Redis** — vision indexing and export run as background jobs, with progress streamed to the client |
| **Computer Vision** | **DeepFace** (face detection, embedding and clustering), **YOLOv8** (object and scene labels), **Pillow + exifread** (EXIF extraction, blur and quality scoring), **OpenCV** |
| **AI orchestration** | **Claude Sonnet 4.6 (Anthropic)** — two specialist agents: a Selection Agent and a Layout Agent, each with Pydantic-validated structured output and a deterministic fallback |
| **Export** | **Pillow** — multi-page PDF generation and a 300 DPI print-ready ZIP archive |
| **Local infrastructure** | **Docker Compose** — Postgres + Redis; backend and frontend run natively for fast iteration |
| **Deployment (V1)** | **Railway** — separate `backend` and `frontend` services across two environments: `production` (git `main`) and `staging` (git `dev`) |
| **Managed data (V1)** | **Supabase** — Postgres, Storage (blob store) and Auth, adopted through existing interface seams |
| **Source control** | **Git / GitHub** — `dev` as the working branch, merged to `main` for production |
| **Testing** | **pytest** — 71 backend tests including a full end-to-end smoke test; **TypeScript `tsc -b`** for frontend correctness |
| **Linting** | **ruff** (Python) and **ESLint** (TypeScript), including a **custom RTL lint rule** |
| **Design workflow** | **Stitch / Figma MCP** → React components in `frontend/src/features/` |

### Architectural principle: Claude as a specialist consultant, not an autopilot

Each call to Claude is short, targeted and bounded:

- **Inputs are metadata JSON — never raw image bytes.** Bytes stay in the local workers.
- **Outputs are validated against Pydantic schemas.** Failed validation triggers a deterministic fallback, not a retry storm.
- **Orchestration code decides the order of calls; Claude decides the content within each call.**

The design deliberately **rejects multi-step autonomous agent loops** for these tasks. The product requires assistive AI, not autonomous AI; agent loops would inflate latency and cost without observable user benefit for what are, in the end, two well-bounded tool-use problems. This decision is documented with its reasoning rather than left implicit — including the condition under which it should be revisited.

## 5. Key Features and Functionality

Features implemented and working:

- **Photo ingestion** from a local folder or uploaded ZIP archive, behind a `PhotoSource` interface designed so that Google Photos, iCloud and WhatsApp sources can be added in V1 without refactoring the pipeline.

- **Automatic vision indexing pipeline** (Celery worker): EXIF extraction, blur and quality scoring, face detection with embedding and clustering into recurring persons, and object/scene labelling via YOLOv8. Runs asynchronously so large libraries do not block the interface.

- **Fast multi-criteria filtering** across date range, detected persons, labels and quality thresholds, with lazily-loaded thumbnails and a masonry photo grid. Target latency is under 5 seconds at 5,000 photos.

- **AI Selection Agent.** Given photo metadata, selection criteria and a target count, Claude returns a scored, reasoned selection with explicit anti-duplication rules. Every response is Pydantic-validated; on validation failure the system falls back to a **deterministic ranker** (blur score weighted by date diversity) rather than failing or retrying blindly.

- **AI Layout Agent.** Produces a full album layout — page grids and per-item placement — using Claude tool-use with a strict JSON schema, guided by golden-ratio composition rules and a chosen style. Falls back to a deterministic 2×2 / 3×2 grid generator.

- **Album management** — create and edit albums, reorder pages, adjust selections, and request new layout suggestions.

- **Dual export path** — a multi-page **PDF** for digital viewing and a **300 DPI print-ready ZIP** for physical printing. DPI compliance is treated as a correctness requirement, not a preference.

- **Hebrew RTL interface throughout**, enforced by a **custom ESLint rule** (`rtl/no-hardcoded-ltr-tailwind`) that errors on physical-direction Tailwind classes (`pl-`, `ml-`, `text-left`, `border-l-`) and requires their logical equivalents (`ps-`, `ms-`, `text-start`, `border-s-`). This makes RTL correctness a build-time guarantee rather than a review checklist item.

- **Response caching for layout suggestions**, keyed on the photo-set hash, page count and style, so that re-rendering a view never re-invokes Claude.

- **End-to-end smoke test** walking the entire MVP flow against the real FastAPI application and a real Postgres test database: ingest a ZIP → search → suggest selection → suggest layout → export PDF → export print ZIP.

## 6. Information Security and Privacy

The system processes personal photographs, which are inherently sensitive. Privacy is addressed structurally rather than by policy.

- **Photo bytes never reach the external AI provider.** All computer vision runs locally via open-source models. The agent layer receives only derived metadata JSON — identifiers, timestamps, person cluster IDs, labels, quality scores. This is the project's core privacy promise and it is preserved unchanged by the planned V1 migration: Supabase Storage will hold the bytes, and the agent layer will still receive metadata only.

- **Face embeddings are stored as derived vectors**, not as retrievable face images, and are used solely to cluster recurring people within a single user's own library.

- **Secrets are environment-based.** `.env` is gitignored and `.env.example` documents each variable with placeholder values. The Anthropic API key is server-side only and never exposed to the browser.

- **Cost and abuse controls on the AI layer** — metadata-only payloads bounded well within a ~32K input-token budget, response caching to prevent redundant calls, and Sonnet rather than Opus as the default model, chosen for sufficient quality at roughly three times lower latency.

- **Validated structured output as a safety boundary.** Because every Claude response is validated against a Pydantic schema before use, a malformed or unexpected model response degrades into a deterministic fallback instead of propagating into the database or the rendered album.

- **Authentication is explicitly deferred to V1** and designed for rather than improvised: the `get_current_user` dependency exists as a stub with all call sites already written against it, so introducing Supabase Auth (JWT verified as a FastAPI dependency) will not touch application logic. The MVP runs as a local single-user development environment, where deferring auth is a scoping decision rather than an omission.

## 7. Planned / Future Features

- **Additional photo sources** — Google Photos, iCloud and WhatsApp export ingestion, implemented behind the existing `PhotoSource` interface.
- **Managed cloud deployment (V1)** — migrate to Supabase for Postgres, blob storage and authentication, and deploy to Railway across paired staging and production environments.
- **`pgvector` for face similarity** — a one-click Supabase extension replacing the current in-application clustering, enabling similarity search at larger library sizes.
- **Interactive layout refinement** — an "iterate until approved" flow driven by an explicit user feedback action, implemented as a single tool-use turn rather than an autonomous loop, consistent with the project's stated agent philosophy.
- **Browser-driven Playwright UI smoke tests**, deferred from the MVP on the reasoning that the backend E2E test already covers every API the frontend calls, and `tsc -b` enforces frontend correctness — so adding Chromium to CI did not justify its cost at this stage.
- **Cloud vision providers** as an optional alternative to local models, designed for as an interface but deliberately not built, since adopting them would compromise the privacy architecture.
- **Accessibility pass** — contrast, keyboard navigation and screen-reader support across the album editing workflow.

## 8. Development Process and Project Management

- **Architecture-first delivery.** A full architectural design document was written before implementation, covering module boundaries, database schema, storage strategy, agent design, folder structure, a phased roadmap, and an explicit register of the largest technical risks. Implementation followed that plan.

- **Phased roadmap (P0–P5)**, each phase a self-contained, committed work unit: scaffold → ingest and index → filter and manual selection → AI selection and layout → export → polish. Commit history maps one-to-one onto these phases.

- **Branch strategy** — `dev` as the integration branch, merged to `main` for production, matching the planned Railway environment topology (`dev` → staging, `main` → production).

- **Decisions are recorded with their rationale, including rejections.** When a set of stack changes was proposed — Flask instead of FastAPI, plain HTML instead of React, CrewAI for the agents — each was triaged individually and the reasoning documented rather than adopted wholesale. FastAPI and React were kept because async validation, typed clients and component state were load-bearing; CrewAI was deferred because the architecture already argues against agent loops for bounded tool-use tasks; Supabase and Railway were adopted because they fit existing interface seams. Documenting a rejected proposal and *why* it was rejected is treated as part of the engineering record.

- **Interface seams as a migration strategy.** `BlobStore`, `PhotoSource` and `get_current_user` were defined as abstractions during the MVP specifically so that the V1 move to managed services would be additive. The deployment document lists precisely which code changes remain before first deploy.

- **Testing and linting as build gates** — `make test` runs the full backend suite including the end-to-end smoke test; `make lint` runs ruff and ESLint, including the custom RTL rule.

- **Reproducible local environment** — `docker-compose.yml` plus a `Makefile` provide a documented setup path: configure, install, start infrastructure, migrate, run.

- **AI-assisted development throughout**, with Claude and Claude Code used for architecture, planning and implementation, and the Stitch / Figma MCP workflow feeding UI design directly into React components.

## 9. Current Status

**The MVP is feature-complete through phase P5 (polish).** Ingestion, vision indexing, filtering, the AI Selection Agent, the AI Layout Agent, album management, dual-format export, the RTL lint rule and a backend end-to-end smoke test are all implemented and wired together.

The system currently runs as a **local development environment**: Docker Compose provides Postgres and Redis, with the FastAPI backend and Vite frontend running natively. The frontend is served at `localhost:5173` and the backend exposes OpenAPI documentation at `/docs`.

**Test coverage:** 71 backend tests across EXIF parsing, image quality scoring, thumbnail generation, the local folder source, the ingest service, the filter API, the vision worker, the selection agent, the layout agent, export generation, health checks, and a full end-to-end flow.

**Recent work** completed the V1 direction: a documented deployment plan for Railway and Supabase, a backend E2E smoke test, the custom RTL ESLint rule, and a build fix preventing TypeScript from emitting JavaScript alongside sources.

**Next milestone (V1):** deploy to Railway, migrate database, storage and authentication to Supabase, and wire the `dev` → staging / `main` → production branch flow. The remaining code changes required before first deploy are enumerated in the deployment document rather than left to be discovered.

**Stated openly:** the application has not yet run in a deployed cloud environment, and authentication is a stub. Both are deliberate MVP scoping decisions with a documented implementation path, not gaps discovered late.

## 10. Summary

**Photo Album Creator** combines full **Full-Stack** development, a working **computer-vision pipeline** built on open-source models, an **AI agent layer** performing genuinely creative tasks — curation and layout design — under strict output validation, a privacy architecture enforced structurally rather than by policy, and an orderly engineering process built on phased delivery, automated testing and documented deployment topology.

What distinguishes the project is the **discipline of its constraints**. Claude is used as a bounded specialist rather than an autopilot, and the decision *not* to build autonomous agent loops is argued explicitly rather than assumed. Every AI response is schema-validated with a deterministic fallback behind it, so the system degrades predictably instead of failing unpredictably. Raw photographs are architecturally prevented from reaching an external provider. RTL correctness is enforced by a custom lint rule rather than left to reviewer attention. Each of these is a case of choosing a guarantee over a convention.

The breadth of development, the technological range spanning vision, agents and full-stack engineering, and the organisational infrastructure supporting it are appropriate to a final project in an AI development certification programme built around **AI-assisted software engineering**.

---

Supporting documents: [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) (architectural design and decision record), [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) (Railway + Supabase topology), [`prompt_creator/Photo_Album_Creator_Prompt_Spec.md`](Photo_Album_Creator_Prompt_Spec.md) (original product specification), [`README.md`](../README.md) (setup and usage).
