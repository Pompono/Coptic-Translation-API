from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Callable

from cachetools import TTLCache
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.responses import JSONResponse

from app.config import Settings, get_settings
from app.translator import TranslatorLoadError, TranslatorRuntimeError, load_models

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("coptic-api")
MAX_BODY_BYTES = 16_384


class TranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    text: str = Field(min_length=1)
    direction: str | None = None
    dialect: str | None = None
    includeConfidence: bool = False

    @property
    def include_confidence(self) -> bool:
        return self.includeConfidence

    @field_validator("text")
    @classmethod
    def trim_and_validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be empty")
        return value

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str | None) -> str | None:
        if value is not None and value not in {"coptic_to_english", "english_to_coptic"}:
            raise ValueError("direction must be coptic_to_english or english_to_coptic")
        return value


class RequestSizeLimitMiddleware:
    """Enforces a body limit for both Content-Length and streamed requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length")
        if length:
            try:
                too_large = int(length) > MAX_BODY_BYTES
            except ValueError:
                await JSONResponse({"error": "Invalid Content-Length header."}, status_code=400)(scope, receive, send)
                return
            if too_large:
                await JSONResponse({"error": "Request body is too large."}, status_code=413)(scope, receive, send)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY_BYTES:
                await JSONResponse({"error": "Request body is too large."}, status_code=413)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay_body():
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_body, send)


class RateLimitMiddleware:
    """Small per-process window counter; ingress should enforce limits at scale."""

    ROUTES = {"/v1/translate", "/api/translate", "/api/translate/en-coptic"}
    WINDOW_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}

    def __init__(self, app, rate: str):
        self.app = app
        match = re.fullmatch(r"\s*(\d+)\s*/\s*(second|minute|hour|day)s?\s*", rate.lower())
        if not match or int(match.group(1)) < 1:
            raise ValueError("rate limit must look like '30/minute'")
        self.limit = int(match.group(1))
        self.window = self.WINDOW_SECONDS[match.group(2)]
        self.requests: TTLCache = TTLCache(maxsize=10_000, ttl=self.window)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST" or scope.get("path") not in self.ROUTES:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        key = client[0] if client else "unknown"
        now = time.monotonic()
        count, reset = self.requests.get(key, (0, now + self.window))
        if reset <= now:
            count, reset = 0, now + self.window
        if count >= self.limit:
            response = JSONResponse(
                {"error": "Rate limit exceeded."},
                status_code=429,
                headers={"Retry-After": str(max(1, int(reset - now)))},
            )
            await response(scope, receive, send)
            return

        self.requests[key] = (count + 1, reset)
        await self.app(scope, receive, send)


def build_app(settings: Settings | None = None, model_loader: Callable | None = None,
              run_in_thread: Callable | None = None) -> FastAPI:
    config = settings or get_settings()
    if config.api_key and len(config.api_key) < 32:
        raise ValueError("COPTIC_API_KEY must contain at least 32 characters")
    load = model_loader or load_models
    offload = run_in_thread or asyncio.to_thread

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        started = time.perf_counter()
        try:
            app.state.models = await offload(
                load,
                config.c2e_model,
                config.e2c_model,
                config.c2e_revision,
                config.e2c_revision,
                config.generation_max_new_tokens,
            )
            app.state.model_load_seconds = time.perf_counter() - started
            app.state.ready = True
            logger.info("Models loaded in %.2fs on %s", app.state.model_load_seconds,
                        getattr(app.state.models, "device", "unknown"))
        except Exception:
            app.state.ready = False
            logger.error("Model loading failed")
            raise
        yield
        app.state.ready = False

    app = FastAPI(title="Coptic Translation API", version="1.0.0", lifespan=lifespan)
    app.state.ready = False
    app.state.model_load_seconds = None
    app.state.cache = TTLCache(maxsize=config.cache_entries, ttl=config.cache_ttl_seconds)
    app.state.inference_lock = asyncio.Semaphore(1)
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(RateLimitMiddleware, rate=config.rate_limit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", "")
        if not request_id or len(request_id) > 80 or not all(ch.isalnum() or ch in "-_." for ch in request_id):
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.2f}"
        return response

    async def authenticate(request: Request) -> None:
        if config.api_key:
            supplied = request.headers.get("X-API-Key", "")
            if not hmac.compare_digest(supplied, config.api_key):
                raise HTTPException(status_code=401, detail="A valid X-API-Key is required.")

    @app.get("/health/live", tags=["health"])
    async def live():
        return {"status": "alive"}

    @app.get("/health/ready", tags=["health"])
    async def ready(request: Request):
        if not request.app.state.ready:
            raise HTTPException(status_code=503, detail="Models are not ready.")
        return {
            "status": "ready",
            "device": getattr(request.app.state.models, "device", "unknown"),
            "model_load_seconds": round(request.app.state.model_load_seconds, 3),
        }

    @app.get("/v1/models", tags=["health"])
    async def models(request: Request, _auth: None = Depends(authenticate)):
        return {
            "coptic_to_english": config.c2e_model,
            "english_to_coptic": config.e2c_model,
            "ready": request.app.state.ready,
        }

    async def translate_body(payload: TranslationRequest, request: Request, direction: str) -> dict:
        if len(payload.text) > config.max_input_chars:
            raise HTTPException(status_code=413, detail=f"text must be at most {config.max_input_chars} characters")
        if not request.app.state.ready:
            raise HTTPException(status_code=503, detail="Models are not ready.")
        try:
            from app.translator import TranslatorInputError, normalize_dialect
            dialect = normalize_dialect(payload.dialect,
                "sahidic" if direction == "coptic_to_english" else "bohairic")
        except TranslatorInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        normalized_text = " ".join(payload.text.split())
        key_src = f"v1\0{direction}\0{dialect}\0{normalized_text.casefold()}\0{payload.include_confidence}"
        cache_key = hashlib.sha256(key_src.encode("utf-8")).hexdigest()
        cached = request.app.state.cache.get(cache_key)
        if cached:
            result = dict(cached)
            result["cached"] = True
            return result

        async with request.app.state.inference_lock:
            # A concurrent request may have populated the cache while this one waited.
            cached = request.app.state.cache.get(cache_key)
            if cached:
                result = dict(cached)
                result["cached"] = True
                return result
            try:
                result = await offload(
                    request.app.state.models.translate,
                    normalized_text,
                    direction,
                    dialect,
                    payload.include_confidence,
                )
            except TranslatorRuntimeError as exc:
                logger.warning("Translation failed request_id=%s error=%s", request.state.request_id, exc)
                raise HTTPException(status_code=502, detail="Translation model failed to produce a result.") from exc
            except TranslatorInputError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            request.app.state.cache[cache_key] = dict(result)
            result["cached"] = False
            return result

    @app.post("/v1/translate", tags=["translation"])
    async def translate(payload: TranslationRequest, request: Request, _auth: None = Depends(authenticate)):
        if payload.direction is None:
            raise HTTPException(status_code=422, detail="direction is required")
        return await translate_body(payload, request, payload.direction)

    @app.post("/api/translate", tags=["compatibility"])
    async def translate_coptic_compat(payload: TranslationRequest, request: Request,
                                      _auth: None = Depends(authenticate)):
        if payload.direction not in (None, "coptic_to_english"):
            raise HTTPException(status_code=422, detail="This endpoint requires coptic_to_english direction.")
        result = await translate_body(payload, request, "coptic_to_english")
        return {key: value for key, value in result.items() if key != "direction" and key != "cached"}

    @app.post("/api/translate/en-coptic", tags=["compatibility"])
    async def translate_english_compat(payload: TranslationRequest, request: Request,
                                       _auth: None = Depends(authenticate)):
        if payload.direction not in (None, "english_to_coptic"):
            raise HTTPException(status_code=422, detail="This endpoint requires english_to_coptic direction.")
        result = await translate_body(payload, request, "english_to_coptic")
        return {key: value for key, value in result.items() if key != "direction" and key != "cached"}

    @app.exception_handler(TranslatorLoadError)
    async def translator_load_error(_: Request, exc: TranslatorLoadError):
        logger.exception("Translator loading error", exc_info=exc)
        return JSONResponse({"error": "Translator models could not be loaded."}, status_code=503)

    return app


app = build_app()
