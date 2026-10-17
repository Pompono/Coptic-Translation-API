# Validation record

This record distinguishes local checks from checks that require the deployment
host or model download. Update the measured values for each release candidate.

## Local change validation

Validated on Windows with Python 3.11.9:

- `python -m pytest -q`: **8 passed**. API tests inject a deterministic fake
  translator; they verify routes, direction defaults, caching, API key checks,
  streamed and character input limits, response headers, weak-key rejection,
  and rate limiting without downloading weights.
- `python -m ruff check app tests scripts`: **passed**.
- `python -m compileall -q app tests scripts`: **passed**.
- Docker image build: **not run**, because Docker is not installed on the local
  machine. CI is configured to build the image on Ubuntu.

## Translation benchmark

No numeric translation benchmark is recorded in source control because the
actual Hugging Face models have not been provisioned in this environment. Use
`python scripts/benchmark.py` and save the emitted JSON under an external
deployment record or an ignored `benchmark-results/` folder. The script
measures actual model-backed API requests; it does not use fake models.

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
- HTTPS termination, authentication secret provisioning, firewall rules,
  backups of the model cache, and EC2 cost controls belong to the operator's
  infrastructure configuration.
