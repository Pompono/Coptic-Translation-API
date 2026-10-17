# Validation record

This record distinguishes local checks from checks that require the deployment
host or model download. Update the measured values for each release candidate.

## Validation environment and CI

The local Windows environment has Python 3.11.9, but does not have Docker or
the project dependencies installed. Installing dependencies from PyPI failed
because DNS/network access to PyPI is unavailable. Therefore no local pytest,
Ruff, Docker build, Hugging Face download, or model-backed translation result
is claimed here. `python -m compileall -q app tests scripts` and `git diff
--check` passed locally.

The first GitHub Actions run for PR #1 failed as expected from two detected
problems: Docker tried to install `requirements.txt` before copying it, and the
`pytest` console-script invocation failed to import the `app` package during
collection. The PR changes copy the manifest before pip install and invoke
tests as `python -m pytest`. CI also now runs a real Hugging Face model smoke
job that downloads both public models, starts the API lifespan, and requests
one translation in each direction. Record the resulting run URL, exact pass or
failure status, and smoke metrics here after that run completes.

## Translation benchmark

The Actions smoke job reports actual model download/startup duration, process
peak RSS through model load and one request in each direction, device, and
sample outputs. This is a smoke check on a shared GitHub-hosted runner, not a
representative EC2 capacity benchmark or translation-quality evaluation. Use
`python scripts/benchmark.py` against the actual container on the selected
Linux/EC2 host; record cold-start time and container peak RSS from cgroup or
`docker stats`, then run repeated warm and expected-concurrency measurements.
Do not treat the Compose 4 GiB limit as validated until those measurements
complete. Set `COPTIC_MEMORY_LIMIT` to the measured peak plus suitable OS and
load headroom.

## Known limits

- Translation quality is experimental and has not been evaluated across a
  representative Coptic corpus.
- The confidence value is a softmax-derived heuristic inherited from the
  referenced implementation, not a calibrated probability.
- Model download and first load time depend on Hugging Face availability and
  host bandwidth. First startup remains unready until both model/tokenizer pairs
  load successfully.
- Default Docker inference is CPU-only. GPU deployment needs a CUDA-compatible
  PyTorch build and host/container driver setup.
- The cache and rate limiter are in-memory and per process. This setup is aimed
  at one process and one host behind a trusted proxy.
- Public Next.js clients cannot safely hold a shared backend API key. Use a
  server-side Next.js route/proxy, keep the key in server-only environment
  configuration, and apply per-user/IP abuse controls at that public edge.
- Both selected Hugging Face model cards currently report AGPL-3.0. Obtain
  legal review of the exact model revisions and hosted-service/source-offer
  obligations before public production use.
- HTTPS termination, authentication secret provisioning, firewall rules,
  backups of the model cache, and EC2 cost controls belong to the operator's
  infrastructure configuration.
