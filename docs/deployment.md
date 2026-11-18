# Deployment

Issue #22. The backend ships as a container (`backend/Dockerfile`), so it runs on any host that
runs Docker images. The frontend goes on a free static host (not covered here). The host
choice is deferred in Grill Decisions; this page compares the options so the human can pick.

**Status: recommendation pending the human's decision.** Nothing is deployed yet.

## The container

```bash
docker build -t hexcoach-backend backend
docker run --rm -p 8000:8000 --env-file backend/.env hexcoach-backend
```

- The configuration is the same environment variables as in dev (`backend/.env.example`). On a
  host, set them as secrets in its dashboard. `.env` is excluded from the image.
- `PORT` picks the listening port (default 8000). Most hosts set it themselves.
- The embedding model (bge-small-en-v1.5, quantized ONNX, 65 MB) is downloaded while the image
  builds, and the container runs with `HF_HUB_OFFLINE=1`. So a cold start never downloads it.
- The container doesn't migrate. Run `uv run backend migrate` from a dev machine before
  deploying a release that adds migrations.
- `CORS_ALLOWED_ORIGINS` must list the frontend's public origin, e.g.
  `https://hexcoach.example`. It is comma-separated and empty by default, so no browser
  origin is allowed until it is set.

## Measured footprint

Docker wasn't available on the machine this was measured on. So the image's runtime was
reproduced without it: the same files the image copies, the same locked `--no-dev` install
(Python 3.13), the model baked into a fixed cache, offline mode, the same `backend serve`
command, and a dummy `DATABASE_URL`. These are resident memory (RSS) figures, on 2026-11-17:

| State | RSS |
| --- | --- |
| API idle (`backend serve`, no model loaded) | ~120 MB |
| API with the model loaded, plus 20 query embeddings | ~370 MB |

The number to plan for is **about 370 MB**. Today the API never loads the model. Once the chat
endpoint (issue #12) embeds questions, the first chat request loads it. Pinning the process to
1 or 2 cores didn't change these figures. Bulk ingestion peaks around 1.2 GB, but it's a manual
step run from a dev machine, never on the host.

On one core, the API started in about 1.6 s, the model loaded in 0.6 s and each query
embedded in about 12 ms. Free tiers give 0.1 vCPU, so expect roughly ten times those times
(an estimate, not measured).

The image itself was not built here. It still needs a `docker build` and a memory check under
`docker stats`.

## Free backend hosts

All checked on 2026-11-17 against each host's own docs. Free tiers change often, so all of
these are **unverified until the account is actually created**.

| Host | Free memory | Fits ~370 MB? | Idle behaviour | Catches |
| --- | --- | --- | --- | --- |
| [Render](https://render.com/docs/free) free web service | 512 MB, 0.1 CPU | Yes, ~140 MB headroom | Spins down after 15 min idle; waking takes ~1 min | 750 instance hours/month; may restart at any time |
| [Koyeb](https://www.koyeb.com/docs/reference/instances) free instance | 512 MB, 0.1 vCPU | Yes, ~140 MB headroom | Scales to zero after 1 h idle; waking takes 1-5 s | Credit card required; Frankfurt or Washington only; Koyeb is joining Mistral AI and the pricing page no longer advertises the free tier (still in the [FAQ](https://www.koyeb.com/docs/faqs/pricing)) |
| [Google Cloud Run](https://cloud.google.com/run/pricing) | Configurable (512 MiB to 1 GiB is fine) | Yes, and memory can be raised | Scales to zero; cold start on each wake-up | Billing account (card) required; free tier is 360,000 GiB-s and 180,000 vCPU-s per month on request-based billing |
| [Fly.io](https://docs.fly.io/about/pricing) | No free tier ($1 trial credit) | 512 MB machine $3.69/month | Machines can auto-stop | [Bills under $5 waived](https://docs.fly.io/about/free-waiver) once a card is added, so in practice free but card-backed |
| [Railway](https://docs.railway.com/pricing/plans) Free plan | 0.5 GB | Barely | Always on, until the credit runs out | $1/month of credit covers about 100 MB-month of RAM, far short of an always-on 370 MB service |
| [Hugging Face Spaces](https://huggingface.co/docs/hub/spaces-overview) | 16 GB CPU Basic | Yes | Sleeps when unused | Docker Spaces now need a paid PRO plan; only static Spaces are free |

## Recommendation (pending the human's decision)

**Render's free web service.** It's the only option that is free, needs no credit card, runs
the Dockerfile directly from the repo (Docker build context `backend`, Dockerfile path
`backend/Dockerfile`), and leaves
about 140 MB of headroom over the measured footprint. The cost is a cold start of about a
minute after 15 idle minutes. That's acceptable for a portfolio demo, and the frontend can
show a "waking up" state.

- **Runner-up: Koyeb.** Same memory, and its cold starts are much faster. But it needs a card,
  and the free tier's future is uncertain after the Mistral acquisition.
- **If 512 MB turns out too tight** (once the agent's real request path is measured with
  #12 merged): Cloud Run, with a 1 GiB service. A demo's traffic should stay well inside
  the free GiB-seconds. It needs a billing account.

## Keep-alive

Supabase pauses Free plan projects that see too little database activity over a week, and
says ["a few user requests to the database each day"](https://supabase.com/docs/guides/platform/free-project-pausing)
is typically enough. It publishes no threshold and no definition of which queries count, so
this is **unverified**. Supabase emails a warning about a week before pausing a project.

- `GET /health` is public. It reads one row of the `cards` table (a real table rather than
  `SELECT 1`, to look like a user query) and answers `{"status": "ok"}`, or 503 when the
  database doesn't answer.
- `.github/workflows/keep-alive.yml` calls it every six hours. It retries for a few minutes,
  so a sleeping host has time to wake. A failed ping fails the run, which GitHub emails
  about.
- Set the repository variable **`KEEPALIVE_URL`** to the full health URL, e.g.
  `https://hexcoach-api.onrender.com/health`. Until it is set, each run pings nothing and
  ends with a "Keep-alive is not configured" warning annotation on the run.
- The pings also wake a sleeping Render instance every six hours. Each one costs roughly
  15 minutes of the 750 free instance hours, which is negligible.
- GitHub runs scheduled workflows only from the default branch. In public repositories it
  disables them after 60 days without repository activity, and then they must be
  re-enabled in the Actions tab.

## Left for the human

- Pick the host and deploy the container with the production environment variables. Point
  `CORS_ALLOWED_ORIGINS` at the frontend's origin.
- Set `KEEPALIVE_URL` in the repository variables.
- In Supabase Auth, add the deployed frontend URL to the site URL and the redirect URLs.
