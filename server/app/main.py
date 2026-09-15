"""FastAPI entry point: ChatKit endpoint, attachment upload, static assets,
health and progress endpoints, optional trainer access code."""
from __future__ import annotations

import hmac
import os
from pathlib import Path

from chatkit.server import StreamingResult
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

from app.chatkit_server import MyChatKitServer
from app.data_store import MAX_IMAGE_ATTACHMENT_BYTES, USER_ID_KEY, MyDataStore

app = FastAPI()
APP_DIR = Path(__file__).resolve().parent
DOCS_DIR = APP_DIR.parent.parent / "docs"
app.mount("/static", StaticFiles(directory=str(APP_DIR)), name="static")
if DOCS_DIR.exists():
    app.mount("/docs", StaticFiles(directory=str(DOCS_DIR)), name="docs")

ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional shared code for the trainers' demonstrator: when ACCESS_CODE is
# set, every stateful endpoint requires the X-Access-Code header.
ACCESS_CODE = os.getenv("ACCESS_CODE", "").strip()

data_store = MyDataStore()
server = MyChatKitServer(store=data_store, attachment_store=data_store)


def _access_denied(request: Request) -> JSONResponse | None:
    if not ACCESS_CODE:
        return None
    given = (request.headers.get("X-Access-Code") or "").strip()
    if not given:
        return JSONResponse(status_code=401, content={"message": "access code required"})
    if not hmac.compare_digest(given, ACCESS_CODE):
        return JSONResponse(status_code=401, content={"message": "invalid access code"})
    return None


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "access_code_required": bool(ACCESS_CODE),
        "doctrine_source": server.orch.doc.source,
        "storage": server.orch.store.backend.name,
        "bank_questions": sum(server.orch.bank.stats().values()),
    })


@app.get("/progress")
async def progress(request: Request) -> Response:
    denied = _access_denied(request)
    if denied:
        return denied
    user_id = request.headers.get(USER_ID_KEY)
    if not user_id:
        return JSONResponse(status_code=400, content={"message": "UserId Missing"})
    return JSONResponse(server.orch.progress_summary(user_id))


@app.api_route("/attachments/{attachment_id}/upload", methods=["PUT", "POST"])
async def upload_attachment(attachment_id: str, request: Request) -> Response:
    denied = _access_denied(request)
    if denied:
        return denied
    # Anti-DoS guard: reject on the ANNOUNCED size before reading the body
    # (a ~150 MB unauthenticated request used to OOM the container).
    max_request_bytes = MAX_IMAGE_ATTACHMENT_BYTES + 1 * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > max_request_bytes:
                return JSONResponse(status_code=413, content={"message": "Upload too large."})
        except ValueError:
            return JSONResponse(status_code=400, content={"message": "Invalid Content-Length."})
    content_type = request.headers.get("content-type")
    content: bytes
    if content_type and content_type.lower().startswith("multipart/form-data"):
        form = await request.form()
        content = b""
        for value in form.values():
            if hasattr(value, "read") and hasattr(value, "filename"):
                content = await value.read()
                content_type = getattr(value, "content_type", None) or content_type
                break
        if not content:
            return JSONResponse(status_code=400, content={"message": "No image file found in multipart upload."})
    else:
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > max_request_bytes:
                return JSONResponse(status_code=413, content={"message": "Upload too large."})
            chunks.append(chunk)
        content = b"".join(chunks)
    await data_store.upload_attachment_bytes(attachment_id, content, content_type)
    return Response(status_code=204)


@app.post("/chatkit")
async def chatkit_endpoint(request: Request) -> Response:
    denied = _access_denied(request)
    if denied:
        return denied
    user_id = request.headers.get(USER_ID_KEY)
    if user_id is None:
        return JSONResponse(status_code=400, content={"message": "UserId Missing"})
    provider = request.headers.get("X-Provider")
    api_key = request.headers.get("X-Provider-Api-Key")
    payload = await request.body()
    result = await server.process(payload, context={USER_ID_KEY: user_id, "provider": provider, "api_key": api_key})
    if isinstance(result, StreamingResult):
        return StreamingResponse(result, media_type="text/event-stream")
    if hasattr(result, "json"):
        return Response(content=result.json, media_type="application/json")
    return JSONResponse(result)
