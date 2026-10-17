# Coptic Translation API

A standalone FastAPI service for Coptic ↔ English translation. It reuses the two
Hugging Face models and the dialect normalization behavior used by
[Pompono/Coptic](https://github.com/Pompono/Coptic) and
[Pompono/Coptic-iOS](https://github.com/Pompono/Coptic-iOS). It does not contain
model weights.

## Models and quality

| Direction | Hugging Face model | Default dialect |
| --- | --- | --- |
| Coptic → English | [`megalaa/coptic-english-translator`](https://huggingface.co/megalaa/coptic-english-translator) | Sahidic |
| English → Coptic | [`megalaa/english-coptic-translator`](https://huggingface.co/megalaa/english-coptic-translator) | Bohairic |

The models are downloaded at first start and remain in the configured Hugging
Face cache. The Docker Compose setup mounts that cache in a named volume, so
restarts reuse the downloaded weights. Set `COPTIC_C2E_MODEL` or
`COPTIC_E2C_MODEL` to a compatible local directory or a different Hugging Face
repository when needed. Set each `*_REVISION` to a commit SHA for repeatable
production builds; `main` is the default for convenient setup.

These are experimental machine translation models. Output can be fluent and
wrong, especially for scripture, liturgy, names, dialect-sensitive text, and
long passages. Check translations with a qualified reader before relying on
them. The optional confidence value follows the reference translator's
token-probability heuristic and is **not calibrated** as a measure of accuracy.

Both Hugging Face model cards identify the weights as AGPL-3.0 licensed:
[Coptic → English](https://huggingface.co/megalaa/coptic-english-translator)
and [English → Coptic](https://huggingface.co/megalaa/english-coptic-translator).
Review the license text and obligations for the exact model revisions and your
distribution and hosted-service design before public production use. In
particular, have counsel assess AGPL-3.0 network-use/source-offer requirements
for the model and any modifications. The repository does not redistribute the
weights; CI downloads them from Hugging Face at test time.

## API

`POST /v1/translate`

```json
{
  "text": "ⲡⲉⲛⲛⲟⲩϯ",
  "direction": "coptic_to_english",
  "dialect": "bohairic"
}
```

`direction` is `coptic_to_english` or `english_to_coptic`. `dialect` is
`sahidic` or `bohairic`; if omitted, the direction's default from the table
above is used. Inputs are limited to 1,200 characters by default (configurable).
Set `includeConfidence: true` to include the inherited, uncalibrated confidence
heuristic. Inputs above 512 model tokens are rejected, and output is capped at
64 new tokens by default (`COPTIC_GENERATION_MAX_NEW_TOKENS`).

Successful response:

```json
{
  "translation": "our God",
  "direction": "coptic_to_english",
  "dialect": "bohairic",
  "cached": false
}
```

The response uses `cached: true` when served from the bounded in-memory cache.
Errors use an HTTP status with an `error` or FastAPI `detail` field. Interactive
API docs are available at `/docs` unless disabled by a front proxy.

Compatibility routes are provided for the current frontends:

- `POST /api/translate` performs Coptic → English and accepts `text`, optional
  `dialect`, and optional `includeConfidence`.
- `POST /api/translate/en-coptic` performs English → Coptic with the same fields.

Both compatibility routes return the `translation`, `dialect`, and optional
`confidence` fields expected by the reference clients.

Health endpoints:

- `GET /health/live` indicates that the process is running.
- `GET /health/ready` returns 200 only after both models finish loading; includes
  device and measured startup model-load time.
- `GET /v1/models` reports configured model IDs and readiness (requires API key
  when configured).

## Run with Docker Compose

Requires Docker Engine and Docker Compose v2. Create a local `.env` from the
example file, edit it, then start the service:

```sh
cp .env.example .env
# Set COPTIC_API_KEY to a long random value before allowing non-local access.
docker compose up --build -d
docker compose logs -f coptic-api
curl http://127.0.0.1:8000/health/ready
```

The port binds to `127.0.0.1` by default. Put an HTTPS reverse proxy such as
Caddy, Nginx, or an AWS ALB in front of it. Configure the proxy to forward
`X-Forwarded-For` only from trusted addresses. The container trusts forwarded
headers from loopback only by default. Set `COPTIC_FORWARDED_ALLOW_IPS` to the
exact reverse-proxy source IPs/networks when needed, and configure that proxy to
overwrite untrusted `X-Forwarded-For` values. Never trust `*` on a public server.
Do not expose the container port directly to the public internet. Set
`COPTIC_API_KEY` to at least 32 characters
and require the `X-API-Key` header for the translation API. Set
`COPTIC_ALLOWED_ORIGINS` to an
exact comma-separated allowlist only if browser clients need cross-origin
access. CORS is disabled by default.

### Public Next.js website authentication

Do not put `COPTIC_API_KEY` in browser JavaScript, a `NEXT_PUBLIC_*` variable,
or a static site's client bundle. Browsers cannot keep a shared secret. Deploy
the Next.js app with a server runtime and proxy translation through a Route
Handler (or another trusted server endpoint):

```ts
// app/api/translate/route.ts (server-side only)
export async function POST(request: Request) {
  const payload = await request.json();
  const upstream = await fetch(`${process.env.COPTIC_API_URL}/v1/translate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": process.env.COPTIC_API_KEY!,
    },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
```

Configure `COPTIC_API_KEY` and `COPTIC_API_URL` as server-only environment
secrets in the Next.js hosting platform. Keep the API private to the proxy when
possible. Authenticate/rate-limit website users at the Next.js edge or gateway:
the backend sees a shared proxy address, so its per-client-IP limiter cannot
distinguish those users. CORS only controls browser cross-origin behavior; it
does not protect the endpoint or replace authentication and abuse controls.

For AWS EC2, use a current Ubuntu LTS or Amazon Linux image, install Docker and
Compose from the official distribution packages, allow inbound HTTPS only at
the security group, and keep port 8000 private to the instance/proxy. Provision
RAM and persistent EBS-backed storage for the Compose `hf-cache` volume based
on measurements on the selected instance. First start needs outbound HTTPS to
Hugging Face to download weights. For a GPU, use a CUDA-enabled host and an
NVIDIA Container Toolkit image/build instead of the CPU-only Dockerfile; GPU
runtime setup depends on the selected EC2 AMI and driver. Keep one API worker
per model copy. Each extra worker loads both models again and multiplies memory
use.

The container runs as an unprivileged user, has a read-only root filesystem,
drops Linux capabilities, has a process limit, and includes a readiness
healthcheck. Compose's `COPTIC_MEMORY_LIMIT` (default `4g`) is a configurable,
unbenchmarked starting value, not a proven requirement or capacity guarantee.
After the real-model smoke test, run repeated cold-start and warm-load tests on
the target EC2 size while recording container peak RSS (for example with
`docker stats` and cgroup memory metrics). Set the limit above observed peak
RSS with operating headroom, then repeat under expected concurrency. Do not
increase replicas/workers until measuring the multiplied model memory.

Inference runs one model call at a time per process. The waiting queue is
bounded by `COPTIC_INFERENCE_QUEUE_LIMIT` (default 8) and
`COPTIC_INFERENCE_QUEUE_TIMEOUT_SECONDS` (default 30); a full or timed-out queue
returns HTTP 503 with `Retry-After`. The default `COPTIC_RATE_LIMIT=30/minute`
is a per-process, per-observed-client-address limit on translation POST routes.
It is not a distributed quota, and behind a shared Next.js proxy it aggregates
all users under the proxy address. Enforce per-user/IP limits at the public
edge; use a shared limiter such as Redis if there are multiple backend
replicas. API key comparison is constant-time. The response cache and limiter
are process-local and reset on restart.

## Run locally

Python 3.11 is recommended. Install CPU PyTorch, then the service dependencies:

```sh
python -m venv .venv
# Activate the virtual environment for your shell, then:
python -m pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

The models load once in application startup. `HF_HOME` controls the persistent
cache location. `HF_TOKEN` is read by Hugging Face Hub when a gated model needs
authentication; no credential belongs in the repository or container image.

## Tests and benchmark

Run request validation, caching, authentication, security-header, dialect, and
normalization tests without downloading model weights:

```sh
python -m pip install -r requirements-dev.txt
pytest -q
ruff check app tests scripts
```

After the service has loaded the actual models, measure uncached sequential
latency and throughput with:

```sh
python scripts/benchmark.py --url http://127.0.0.1:8000 --repeats 5
```

The report includes the API process's measured model startup load time, device,
warm request p50/p95, min/max/mean latency, cache counts, and sequential
throughput across both translation directions. The inputs are short, practical
phrases; they do not establish translation accuracy or long-passage capacity.
Run it on the intended Linux host after the cache has been populated and retain
the JSON output as deployment evidence. This repository does not claim fixed
latency figures because CPU, GPU, memory bandwidth, network download speed,
model revisions, and host contention change the result.

## Tests and benchmark status

See [docs/validation.md](docs/validation.md) for checks performed for this
repository change and items that need a provisioned Linux host.
