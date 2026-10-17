"""Download the configured Hugging Face models and exercise both directions."""

from __future__ import annotations

import json
import os
import resource
import time
import asyncio
from datetime import datetime, timezone

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import build_app


def peak_rss_mib() -> float:
    # GitHub Actions and the documented deployment target are Linux.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main() -> None:
    c2e_model = os.getenv("COPTIC_C2E_MODEL", "megalaa/coptic-english-translator")
    e2c_model = os.getenv("COPTIC_E2C_MODEL", "megalaa/english-coptic-translator")
    c2e_revision = os.getenv("COPTIC_C2E_REVISION", "main")
    e2c_revision = os.getenv("COPTIC_E2C_REVISION", "main")

    app = build_app(Settings(
        _env_file=None,
        c2e_model=c2e_model,
        e2c_model=e2c_model,
        c2e_revision=c2e_revision,
        e2c_revision=e2c_revision,
    ))

    async def exercise_api() -> tuple[float, list[dict[str, object]], str]:
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://smoke") as client:
                translations = []
                samples = (
                    ("ⲁⲙⲏⲛ", "coptic_to_english", "bohairic"),
                    ("amen", "english_to_coptic", "bohairic"),
                )
                for text, direction, dialect in samples:
                    request_started = time.perf_counter()
                    response = await client.post("/v1/translate", json={
                        "text": text, "direction": direction, "dialect": dialect,
                    })
                    if response.status_code != 200:
                        raise RuntimeError(f"{direction} returned HTTP {response.status_code}: {response.text}")
                    translation = response.json()["translation"]
                    if not translation.strip():
                        raise RuntimeError(f"Empty translation for {direction}")
                    translations.append({
                        "direction": direction,
                        "dialect": dialect,
                        "elapsed_seconds": round(time.perf_counter() - request_started, 3),
                        "translation": translation,
                    })
            return app.state.model_load_seconds, translations, app.state.models.device

    load_seconds, translations, device = asyncio.run(exercise_api())

    print(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "models": {"coptic_to_english": c2e_model, "english_to_coptic": e2c_model},
        "revisions": {"coptic_to_english": c2e_revision, "english_to_coptic": e2c_revision},
        "device": device,
        "download_and_model_load_seconds": round(load_seconds, 3),
        "process_peak_rss_mib_after_load_and_smoke_translations": round(peak_rss_mib(), 1),
        "translations": translations,
        "note": "Smoke validation only; output presence is not a measure of translation quality.",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
