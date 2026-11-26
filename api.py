import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Any
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
import uvicorn
from src.config import (
    APIFY_API_TOKEN,
    DATA_RETENTION_DAYS,
    DEFAULT_SEARCH_PHRASE,
    ENABLE_CACHE,
    GEMINI_API_KEY,
    GROQ_API_KEY,
    MAX_COMMENTS_PER_POST,
    OUTPUTS_DIR,
    SERPER_API_KEY,
)
from src.pipeline import run_pipeline
from src.schemas import DataSourceMode, PipelineRunResult, RankedInfluencer
from src.similar_profiles import discover_similar_profiles
from src.stage6_export import result_to_csv_str, result_to_json_str, save_outputs


def _slugify(phrase: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", phrase.lower()).strip("_") or "results"


def _mask_presence(value: str) -> dict[str, Any]:
    cleaned = (value or "").strip()
    if not cleaned:
        return {"configured": False, "preview": ""}
    suffix = cleaned[-4:] if len(cleaned) >= 8 else ""
    return {"configured": True, "preview": f"••••{suffix}" if suffix else "Configured"}


def _build_pipeline_kwargs(body: dict[str, Any]) -> dict[str, Any]:
    raw_mode = str(body.get("mode") or DataSourceMode.LIVE_API.value).strip()
    mode = DataSourceMode(raw_mode)

    supplied_urls = body.get("supplied_urls") or []
    if isinstance(supplied_urls, str):
        supplied_urls = [u.strip() for u in supplied_urls.splitlines() if u.strip()]

    def _opt_key(name: str) -> str | None:
        val = body.get(name)
        if val is None:
            return None
        stripped = str(val).strip()
        return stripped if stripped else None

    max_comments = body.get("max_comments_per_post")
    return {
        "raw_phrase": body.get("phrase") or DEFAULT_SEARCH_PHRASE,
        "mode": mode,
        "supplied_urls": supplied_urls,
        "gemini_api_key": _opt_key("gemini_api_key"),
        "apify_token": _opt_key("apify_token"),
        "serper_api_key": _opt_key("serper_api_key"),
        "groq_api_key": _opt_key("groq_api_key"),
        "max_comments_per_post": int(max_comments) if max_comments else None,
        "use_cache": bool(body.get("use_cache", ENABLE_CACHE)),
    }


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def get_config(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "default_phrase": DEFAULT_SEARCH_PHRASE,
            "data_retention_days": DATA_RETENTION_DAYS,
            "defaults": {
                "max_comments_per_post": MAX_COMMENTS_PER_POST,
                "use_cache": ENABLE_CACHE,
            },
            "credentials": {
                "serper": _mask_presence(SERPER_API_KEY),
                "groq": _mask_presence(GROQ_API_KEY),
                "gemini": _mask_presence(GEMINI_API_KEY),
                "apify": _mask_presence(APIFY_API_TOKEN),
            },
        }
    )


async def get_latest(request: Request) -> JSONResponse:
    if not OUTPUTS_DIR.exists():
        return JSONResponse({"result": None})
    json_files = sorted(
        OUTPUTS_DIR.glob("*_results.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in json_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            parsed = PipelineRunResult(**payload)
            return JSONResponse({"result": parsed.model_dump(mode="json")})
        except Exception:
            continue
    return JSONResponse({"result": None})


def _safe_save_outputs(result: PipelineRunResult) -> None:
    """Persist outputs locally when disk is writable without failing read-only containers."""
    try:
        save_outputs(result, OUTPUTS_DIR, file_prefix=f"{_slugify(result.search_phrase)}_results")
    except Exception:
        return


async def discover_sync(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        kwargs = _build_pipeline_kwargs(body)
        result = await asyncio.to_thread(run_pipeline, **kwargs)
        _safe_save_outputs(result)
        return JSONResponse(result.model_dump(mode="json"))
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=500)


def _sse_frame(event: str, data: Any) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


async def discover_stream(request: Request) -> StreamingResponse:
    body = await request.json()
    try:
        kwargs = _build_pipeline_kwargs(body)
    except ValueError as exc:
        async def _err_stream():
            yield _sse_frame("error", {"detail": str(exc)})
        return StreamingResponse(_err_stream(), media_type="text/event-stream", status_code=400)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def _on_progress(step: int, message: str) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait,
            ("progress", {"step": step, "total_steps": 6, "message": message}),
        )

    def _worker() -> None:
        try:
            result = run_pipeline(**kwargs, on_progress=_on_progress)
            _safe_save_outputs(result)
            loop.call_soon_threadsafe(
                queue.put_nowait,
                ("complete", result.model_dump(mode="json")),
            )
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, ("error", {"detail": str(exc)}))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, ("done", None))

    threading.Thread(target=_worker, daemon=True).start()

    async def _event_generator():
        while True:
            try:
                event_type, payload = await asyncio.wait_for(queue.get(), timeout=10.0)
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
                continue
            if event_type == "done":
                break
            yield _sse_frame(event_type, payload)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def export_csv(request: Request) -> Response:
    try:
        body = await request.json()
        result = PipelineRunResult(**body)
        slug = _slugify(result.search_phrase)
        csv_text = result_to_csv_str(result)
        return Response(
            content=csv_text.encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{slug}_results.csv"'},
        )
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


async def export_json(request: Request) -> Response:
    try:
        body = await request.json()
        result = PipelineRunResult(**body)
        slug = _slugify(result.search_phrase)
        json_text = result_to_json_str(result)
        return Response(
            content=json_text.encode("utf-8"),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{slug}_results.json"'},
        )
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


async def find_similar(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        phrase = str(body.get("phrase") or DEFAULT_SEARCH_PHRASE).strip()
        raw_seeds = body.get("seed_influencers") or []
        seeds = [RankedInfluencer(**s) for s in raw_seeds]
        if not seeds:
            return JSONResponse({"detail": "At least one seed profile is required."}, status_code=400)

        serper_override = str(body.get("serper_api_key") or "").strip() or None
        gemini_override = str(body.get("gemini_api_key") or "").strip() or None
        resolved_serper = (serper_override if serper_override is not None else SERPER_API_KEY).strip()
        if not resolved_serper:
            return JSONResponse(
                {"detail": "SERPER_API_KEY is required to find similar LinkedIn profiles."},
                status_code=400,
            )

        exclude_urls = {str(u) for u in (body.get("exclude_urls") or []) if u}
        limit = max(1, min(20, int(body.get("limit") or 10)))
        use_cache = bool(body.get("use_cache", ENABLE_CACHE))

        similar_profiles, warnings = await asyncio.to_thread(
            discover_similar_profiles,
            phrase=phrase,
            seed_influencers=seeds,
            exclude_urls=exclude_urls,
            serper_api_key=serper_override,
            gemini_api_key=gemini_override,
            use_cache=use_cache,
            limit=limit,
        )
        return JSONResponse(
            {
                "similar_profiles": [sp.model_dump(mode="json") for sp in similar_profiles],
                "warnings": warnings,
            }
        )
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


routes = [
    Route("/api/health", health, methods=["GET"]),
    Route("/api/config", get_config, methods=["GET"]),
    Route("/api/latest", get_latest, methods=["GET"]),
    Route("/api/discover", discover_sync, methods=["POST"]),
    Route("/api/discover/stream", discover_stream, methods=["POST"]),
    Route("/api/similar", find_similar, methods=["POST"]),
    Route("/api/export/csv", export_csv, methods=["POST"]),
    Route("/api/export/json", export_json, methods=["POST"]),
]

_raw_cors = os.getenv("CORS_ORIGINS", "*").strip()
_cors_origins = (
    ["*"]
    if _raw_cors == "*" or not _raw_cors
    else [origin.strip().rstrip("/") for origin in _raw_cors.split(",") if origin.strip()]
)

app = Starlette(routes=routes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0" if os.getenv("PORT") else "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
