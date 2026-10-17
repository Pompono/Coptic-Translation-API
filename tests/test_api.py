import asyncio
import os
from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient
import pytest

from app.config import Settings
from app.main import build_app

if os.name == "nt":
    # The sandboxed Windows Proactor loop's internal socketpair blocks; Selector
    # keeps the same ASGI path without that platform-specific setup socket.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class FakeModels:
    device = "cpu"

    def __init__(self):
        self.calls = []

    def translate(self, text, direction, dialect, include_confidence=False):
        self.calls.append((text, direction, dialect))
        result = {"translation": f"result:{text}", "direction": direction, "dialect": dialect}
        if include_confidence:
            result["confidence"] = 0.75
        return result


@asynccontextmanager
async def make_client(settings=None):
    models = FakeModels()

    async def run_inline(function, *args):
        return function(*args)

    app = build_app(
        settings or Settings(_env_file=None),
        model_loader=lambda *args: models,
        run_in_thread=run_inline,
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, models


def test_ready_and_translate_both_directions_and_cache():
    async def scenario():
        async with make_client() as (client, models):
            assert (await client.get("/health/ready")).json()["status"] == "ready"
            c2e = await client.post("/v1/translate", json={
                "text": "ⲡⲉⲛⲛⲟⲩϯ", "direction": "coptic_to_english", "dialect": "bohairic"
            })
            assert c2e.status_code == 200, c2e.text
            assert c2e.json()["translation"] == "result:ⲡⲉⲛⲛⲟⲩϯ"
            assert c2e.json()["cached"] is False
            e2c = await client.post("/v1/translate", json={"text": "amen", "direction": "english_to_coptic"})
            assert e2c.json()["dialect"] == "bohairic"
            again = await client.post("/v1/translate", json={"text": "amen", "direction": "english_to_coptic"})
            assert again.json()["cached"] is True
            assert len(models.calls) == 2

    asyncio.run(scenario())


def test_auth_and_limits():
    async def scenario():
        settings = Settings(_env_file=None, api_key="private-key-that-is-at-least-32-chars", max_input_chars=4)
        async with make_client(settings) as (client, _):
            payload = {"text": "love", "direction": "english_to_coptic"}
            unauthorized = await client.post("/v1/translate", json=payload)
            assert unauthorized.status_code == 401, unauthorized.text
            headers = {"X-API-Key": "private-key-that-is-at-least-32-chars"}
            oversized = await client.post("/v1/translate", json={**payload, "text": "longer"}, headers=headers)
            assert oversized.status_code == 413
            invalid = await client.post("/v1/translate", json={**payload, "direction": "invalid"}, headers=headers)
            assert invalid.status_code == 422

    asyncio.run(scenario())


def test_rate_limit_returns_retry_after():
    async def scenario():
        async with make_client(Settings(_env_file=None, rate_limit="1/minute")) as (client, _):
            first = await client.post("/v1/translate", json={"text": "amen", "direction": "english_to_coptic"})
            second = await client.post("/v1/translate", json={"text": "amen", "direction": "english_to_coptic"})
            assert first.status_code == 200
            assert second.status_code == 429
            assert int(second.headers["Retry-After"]) > 0

    asyncio.run(scenario())


def test_streamed_oversized_body_is_rejected_and_short_api_key_fails_closed():
    async def scenario():
        async def chunks():
            yield b'{"text":"'
            yield b"a" * 17_000
            yield b'","direction":"english_to_coptic"}'

        async with make_client() as (client, _):
            response = await client.post(
                "/v1/translate",
                content=chunks(),
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 413

    asyncio.run(scenario())
    with pytest.raises(ValueError, match="at least 32 characters"):
        build_app(Settings(_env_file=None, api_key="too-short"))


def test_full_inference_queue_rejects_new_requests_without_building_an_unbounded_wait():
    async def scenario():
        settings = Settings(_env_file=None, inference_queue_limit=0)

        async def delayed(function, *args):
            await asyncio.sleep(0.15)
            return function(*args)

        models = FakeModels()
        app = build_app(settings, model_loader=lambda *args: models, run_in_thread=delayed)
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                first = asyncio.create_task(client.post("/v1/translate", json={
                    "text": "amen", "direction": "english_to_coptic"
                }))
                await asyncio.sleep(0.02)
                rejected = await client.post("/v1/translate", json={
                    "text": "peace", "direction": "english_to_coptic"
                })
                completed = await first
                assert completed.status_code == 200
                assert rejected.status_code == 503
                assert rejected.headers["Retry-After"] == "5"

    asyncio.run(scenario())


def test_compatibility_endpoints_and_security_headers():
    async def scenario():
        async with make_client() as (client, _):
            response = await client.post("/api/translate", json={
                "text": "ⲁⲙⲏⲛ", "dialect": "sahidic", "includeConfidence": True
            })
            assert response.status_code == 200, response.text
            assert "direction" not in response.json()
            assert response.json()["confidence"] == 0.75
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["Cache-Control"] == "no-store"
            reverse = await client.post("/api/translate/en-coptic", json={"text": "amen"})
            assert reverse.status_code == 200

    asyncio.run(scenario())
