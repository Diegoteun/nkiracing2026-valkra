# Vercel JSON upload for NK prequal data

**Date:** 2026-10-27  
**Status:** Approved for implementation pending user review of this spec

## Problem

Prequal dashboard data lives in `data/valkra-nk-prequal.json` and is loaded by the page from GitHub raw. Updating it today means committing that file by hand (or running the model pipeline). A few trusted people need a simple password-gated page to upload a replacement JSON so everyone sees the new stand.

## Goals

- Password-protected `/upload` page on Vercel
- Upload replaces `data/valkra-nk-prequal.json` on `main` via GitHub Contents API
- Existing dashboard keeps fetching GitHub raw (no second source of truth)
- Host both the dashboard and the upload UI on the same Vercel project

## Non-goals (v1)

- User accounts / per-user auth
- Rebuilding the embedded HTML copy inside `valkra-nk-prequal.html`
- CSV upload
- Wiring the dashboard `#beheer` panel to the new API (can add `uploadUrl` later)
- Changing the Python model / morning automation

## Architecture

```
Browser                  Vercel                     GitHub
───────                  ──────                     ──────
/                        static HTML (dashboard)
/upload                  static HTML (upload form)
                         │
                         │ POST JSON + password
                         ▼
                       /api/upload  ──commit──►  data/valkra-nk-prequal.json (main)
                         ▲
                         │ env: UPLOAD_PASSWORD, GITHUB_TOKEN
```

Dashboard continues to use:

`https://raw.githubusercontent.com/Diegoteun/nkiracing2026-valkra/main/data/valkra-nk-prequal.json`

(optional override via `VALKRA_PREQUAL_CONFIG.dataUrl`)

## Project layout

| Path | Role |
| :--- | :--- |
| `public/index.html` | Dashboard (from current `site/valkra-nk-prequal.html`, or rewrite) |
| `public/upload.html` | Upload UI at `/upload` (rewrite `/upload` → this file) |
| `api/upload.js` | Serverless handler |
| `vercel.json` | Rewrites + static config |
| Existing `data/`, `model/`, `site/` | Unchanged as source of truth / build pipeline |

Keep `site/` as the build output from `model/build.py`. For Vercel, either:

- Copy/symlink dashboard into `public/` as part of deploy config, or
- Point Vercel `outputDirectory` / rewrites so `/` serves `site/valkra-nk-prequal.html`

Prefer: `public/` for upload page + vercel rewrites; dashboard served from `site/` via rewrite so `build.py` does not need to know about Vercel.

## Upload page behaviour

1. Prompt for shared password (session: keep in `sessionStorage` after first OK so re-uploads in the same tab don’t re-prompt every time; clear on tab close).
2. File picker accepting `.json` / `application/json`.
3. Client-side parse + same structural checks as dashboard `#beheer` (`meta`, `forecast`, `drivers`, etc.).
4. On valid file: `POST /api/upload` with JSON body `{ password, data }` (or multipart; JSON body preferred for simplicity, ~83KB today).
5. Show success with `meta.generated_at`, or a clear error (wrong password, invalid shape, GitHub failure).

UI: minimal, matches existing Valkra dashboard tone (dark, compact). No need for a full design system.

## API: `POST /api/upload`

**Request:** JSON `{ "password": string, "data": object }`  
**Auth:** `password` must equal `process.env.UPLOAD_PASSWORD` (constant-time compare).  
**Validation:** Reject if required top-level keys missing (reuse the same field list as the dashboard `problems()` helper).  
**GitHub:** Update file at `data/valkra-nk-prequal.json` on branch `main` using Contents API (GET sha → PUT content). Commit message like `Update prequal data (upload <generated_at>)`.  
**Response:** `200 { ok: true, generated_at }` or `4xx/5xx { ok: false, error }`.

**Env vars (Vercel project settings, not in git):**

| Name | Purpose |
| :--- | :--- |
| `UPLOAD_PASSWORD` | Shared secret (`V@lkra!` for this team) |
| `GITHUB_TOKEN` | PAT with Contents: Read and write on this repo |
| `GITHUB_REPO` | Default `Diegoteun/nkiracing2026-valkra` |
| `GITHUB_BRANCH` | Default `main` |
| `GITHUB_PATH` | Default `data/valkra-nk-prequal.json` |

## Security

- Never commit password or token
- Password check only on server
- No listing of existing secrets in responses
- Body size is fine for current JSON (~100KB); Vercel hobby limit is ample
- Rate limiting: not in v1; shared password is the control

## Ops / deploy

1. Connect repo to Vercel
2. Set env vars
3. Create a fine-grained GitHub PAT (contents write on this repo only)
4. Deploy; smoke-test `/`, `/upload`, upload a known-good JSON, confirm raw URL updates

## Success criteria

- Visiting `/upload` without password cannot change the repo
- Valid JSON + correct password updates `data/valkra-nk-prequal.json` on `main`
- Dashboard (on Vercel or elsewhere) shows new data after GitHub raw refresh
- Invalid JSON and wrong password fail with a clear message and do not write
