# Photo Album Creator

AI-powered web app that turns scattered photo libraries (Google Photos, iCloud, WhatsApp exports, local folders) into a finished photo album — digital flipbook and/or print-ready files.

- **Spec:** [`prompt_creator/Photo_Album_Creator_Prompt_Spec.md`](prompt_creator/Photo_Album_Creator_Prompt_Spec.md)
- **Architecture:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **MVP scope:** Local folder source only · open-source vision (DeepFace + YOLOv8) · local dev only.

## Stack

| Layer | Tech |
|---|---|
| Frontend | React 18 + TypeScript + Vite + Tailwind + i18next (Hebrew RTL) |
| Backend | Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic |
| Async jobs | Celery + Redis |
| Database | Postgres 16 |
| Vision | DeepFace (faces), YOLOv8 (labels), Pillow + exifread (EXIF/quality) |
| AI orchestration | Claude Sonnet 4.6 (selection + layout agents) |
| Export | Pillow (multi-page PDF + 300 DPI print ZIP) |

## Quickstart

Prerequisites: Docker, Python 3.12+, Node 20+.

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY

# 2. Install dependencies
make install

# 3. Start Postgres + Redis
make up

# 4. Apply database migrations
make migrate

# 5. Run backend + frontend together
make dev
```

Open <http://localhost:5173>. Backend OpenAPI docs at <http://127.0.0.1:8000/docs>.

To run the vision worker (needed once you start ingesting photos):

```bash
make worker
```

## Repository layout

```
backend/    FastAPI app, Celery workers, SQLAlchemy models, agents
frontend/   React + Vite SPA
docs/       Architecture & design docs
prompt_creator/  Original product spec
```

See `docs/ARCHITECTURE.md` for the detailed module map.

## Development

```bash
make test    # backend pytest + frontend vitest
make lint    # ruff + eslint
make clean   # remove caches
```

### End-to-end smoke

`backend/tests/test_e2e_smoke.py` walks the full MVP flow against the FastAPI app
and real Postgres test DB: ingest a ZIP → search → suggest selection →
suggest layout → export PDF → export print ZIP. Runs as part of `make test`.

A browser-driven Playwright UI smoke is deferred to V1. The backend smoke covers
every API the frontend calls, and `tsc -b` enforces frontend code correctness;
adding Chromium to CI for marginal extra coverage didn't justify the cost.

### RTL lint rule

`frontend/eslint.config.js` registers `rtl/no-hardcoded-ltr-tailwind`, which
errors on physical-direction Tailwind classes (`pl-`, `ml-`, `text-left`,
`border-l-`, etc.). Use the logical variants (`ps-`, `ms-`, `text-start`,
`border-s-`) so the same JSX renders correctly in Hebrew and English.

## Status

MVP feature-complete through P5 polish — ingest, vision indexing, filter,
selection agent, layout agent, export, RTL lint rule, and a backend E2E smoke
test are all wired up. See `docs/ARCHITECTURE.md` §10 for the phase map.
