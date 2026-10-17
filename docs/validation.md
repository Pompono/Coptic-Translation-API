# Validation record

This record separates CI smoke checks from measurements that still need to be
collected on the target Linux/EC2 host.

## CI and local checks

GitHub Actions run for commit `56174ff` completed successfully:

- [Workflow run 38994370166](https://github.com/Pompono/Coptic-Translation-API/actions/runs/38994370166): `tests`, `docker-build`, and `model-smoke` all passed.
- Unit/API tests: **10 passed**; Ruff reported **All checks passed**.
- Docker Buildx image build completed successfully.
- Docker Compose configuration parsed successfully.
- A built container with a read-only root filesystem ran as UID 10001, imported
  the application, created `/models/hub` in a fresh named volume, and wrote and
  removed a file there successfully.
- The model smoke job downloaded both public Hugging Face models, started the
  API lifespan, and received successful HTTP translations in both directions.

The initial CI runs exposed the Dockerfile copy-order bug, `pytest` console
script import behavior, missing smoke-job dependencies, and a smoke script
import-path issue. A first Docker volume check also assumed `/models/hub`
already existed on a fresh volume. Those issues were corrected; the latest
workflow run linked above passed all jobs and runtime checks.

The local Windows environment has Python 3.11.9, but does not have Docker or
the project dependencies installed. Installing dependencies failed because
DNS/network access to PyPI was unavailable. No local Docker build or runtime
is claimed. Local `python -m compileall -q app tests scripts` and
`git diff --check` passed.

## Real-model smoke measurements

Run 38994370166 used the CPU GitHub-hosted Ubuntu runner with the current
`main` revisions of:

- `megalaa/coptic-english-translator`
- `megalaa/english-coptic-translator`

It reported:

- Both model downloads and startup: **13.768 seconds**.
- Process peak RSS after model loading and the two smoke requests: **1,063.7
  MiB**.
- Coptic → English (`ⲁⲙⲏⲛ`, Bohairic): **1.520 seconds**, result `Amen.`.
- English → Coptic (`amen`, Bohairic): **0.196 seconds**, result `ⲁⲙⲏⲛ`.
- Device: CPU.

These are one-shot smoke measurements on a shared GitHub runner. They prove
that the tested revisions downloaded and generated nonempty output through the
API, but they do not prove translation quality, characterize p95 latency, or
measure a Docker cgroup/EC2 peak. Re-run against pinned model commit revisions
before a production release.

## Memory and deployment benchmark

Compose makes its limit configurable with `COPTIC_MEMORY_LIMIT`; the current
default is `2g`, about twice the smoke job's observed process RSS. This is a
provisional starting point, not a validated Docker or EC2 capacity value. On
the intended instance, record memory during cold download/load, both
directions, maximum-length input, repeated warm traffic, and expected
concurrency. Use `docker stats` and the container's cgroup `memory.peak`, then
set the Compose limit above the measured peak with room for OS/container
overhead. Also measure disk consumed by the Hugging Face volume. One worker and
one concurrent model inference are configured; extra workers or replicas each
load another copy of both models.

Suggested Linux/EC2 validation after setting a strong `COPTIC_API_KEY` in the
server-only `.env` file:

```sh
docker compose up --build -d
docker compose ps
docker compose logs -f coptic-api
curl http://127.0.0.1:8000/health/ready
docker stats --no-stream coptic-api
python scripts/benchmark.py --url http://127.0.0.1:8000 --api-key "$COPTIC_API_KEY" --repeats 30
```

The benchmark report captures API startup time, latency distribution, cache
hits, and sequential throughput. For container memory, sample `docker stats`
while requests run and read `memory.peak` from the container's cgroup after the
run. Keep the API bound to localhost/private networking and expose only HTTPS
through the trusted proxy. Never put the API key in public browser code.

## Production limitations and gates

- Translation quality has not been evaluated over a representative Coptic
  corpus. Smoke outputs are not a quality score; obtain qualified review before
  relying on translations.
- The confidence field is an inherited softmax-derived heuristic and is not a
  calibrated probability.
- The response cache and per-process IP limiter are in-memory and not shared
  across replicas. A public Next.js site needs a server-side proxy; keep the
  shared backend API key in server-only configuration, and authenticate or
  rate-limit individual website users at the public edge. Behind a shared
  proxy, backend per-IP limits aggregate users under that proxy address.
- Both [Coptic → English](https://huggingface.co/megalaa/coptic-english-translator)
  and [English → Coptic](https://huggingface.co/megalaa/english-coptic-translator)
  model cards currently report AGPL-3.0. Get legal review of the exact pinned
  revisions and hosted-service/source-offer obligations before public
  production use.
- HTTPS termination, secret provisioning, firewall/security-group rules,
  persistent cache-volume backups, and EC2 cost controls remain operator
  responsibilities.
