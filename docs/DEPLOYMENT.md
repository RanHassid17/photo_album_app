# Deployment — Railway + Supabase (V1)

This is the go-live plan for Photo Album Creator. It does **not** change the local
dev workflow (`make dev` still runs everything locally against Docker Postgres/Redis).
See `ARCHITECTURE.md` §13 for the rationale.

## Topology

```
Railway project: photo-album-app
├── environment: production
│   ├── service: backend   ← git branch  main   (root dir: backend/)
│   └── service: frontend  ← git branch  main   (root dir: frontend/)
└── environment: staging
    ├── service: backend   ← git branch  dev    (root dir: backend/)
    └── service: frontend  ← git branch  dev    (root dir: frontend/)
```

- **`main` → production**, **`dev` → staging.** Push to `dev` auto-deploys staging;
  merge `dev → main` auto-deploys production.
- **backend** and **frontend** are separate services (independent build, scale,
  redeploy). Build config is in `backend/railway.json` and `frontend/railway.json`.
- **Postgres** comes from **Supabase**, not a Railway service (§13.2).
- **Redis/Celery** for cloud async indexing is a Railway plugin (or deferred until
  cloud indexing is needed).

## Environment variables (set per Railway environment — staging ≠ production)

| Variable | Service | Source |
|---|---|---|
| `ANTHROPIC_API_KEY` | backend | Anthropic console |
| `DATABASE_URL` | backend | Supabase → Project Settings → Database (pooled connection string) |
| `SUPABASE_URL` | backend, frontend | Supabase project |
| `SUPABASE_ANON_KEY` | frontend | Supabase → API |
| `SUPABASE_SERVICE_ROLE_KEY` | backend | Supabase → API (secret — backend only) |
| `PHOTO_STORAGE_BUCKET` | backend | Supabase Storage bucket name |
| `VITE_API_BASE_URL` | frontend | URL of the paired backend service |

Never commit these. Local values stay in `.env` (gitignored).

## One-time setup

> The Railway login/account step needs the project owner's credentials — run it
> yourself. Everything after linking builds from the committed `railway.json`.

1. **Supabase:** create a project (one for staging, one for production, or one
   project with two schemas). Grab the connection string + API keys. Enable
   `pgvector` if/when face-similarity search lands (§4).
2. **Railway:** `railway login`, then create the `photo-album-app` project.
3. Create the **production** and **staging** environments.
4. In each environment add two services from this GitHub repo:
   - **backend** — Root Directory `backend/`, watch branch = the environment's branch.
   - **frontend** — Root Directory `frontend/`, watch branch = the environment's branch.
   Railway reads `railway.json` in each root directory for build/start commands.
5. Set the branch trigger: production services → `main`, staging services → `dev`.
6. Add the environment variables above (per environment).
7. Run backend migrations against Supabase: `alembic upgrade head` (once per env).

## Code changes still required before first deploy (tracked as V1 work)

These are **designed for** in the MVP but not yet implemented (§13.2):

- [ ] `SupabaseBlobStore` implementing the `BlobStore` interface (`backend/app/storage/`).
- [ ] Supabase Auth JWT verification replacing the `get_current_user` stub.
- [ ] Point `DATABASE_URL` at Supabase; confirm Alembic migrations apply cleanly.
- [ ] Frontend `VITE_API_BASE_URL` wiring (currently assumes localhost backend).
- [ ] Decide Redis/Celery hosting (Railway plugin vs. deferred).
