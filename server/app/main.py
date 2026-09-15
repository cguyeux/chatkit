

from chatkit.server import StreamingResult
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.data_store import USER_ID_KEY, MyDataStore, MAX_IMAGE_ATTACHMENT_BYTES
from app.chatkit_server import MyChatKitServer

app = FastAPI()
APP_DIR = Path(__file__).resolve().parent
DOCS_DIR = APP_DIR.parent.parent / "docs"
app.mount("/static", StaticFiles(directory=str(APP_DIR)), name="static")
if DOCS_DIR.exists():
    app.mount("/docs", StaticFiles(directory=str(DOCS_DIR)), name="docs")

# Add CORS to allow our server to be called from local front-end
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

data_store = MyDataStore()
server = MyChatKitServer(store=data_store, attachment_store=data_store)


@app.api_route("/attachments/{attachment_id}/upload", methods=["PUT", "POST"])
async def upload_attachment(attachment_id: str, request: Request) -> Response:
    # Garde anti-DoS : rejeter sur la taille ANNONCEE avant de lire le corps.
    # Sans cela, `await request.body()` / `request.form()` bufferisent tout le
    # fichier en memoire avant que la limite applicative (verifiee plus bas dans
    # upload_attachment_bytes) ne s'applique, ce qui permet a une requete non
    # authentifiee de ~150 Mo de faire tomber le container (OOM). Mesure P57.7,
    # 2026-09-05 : plancher entre 50 et 150 Mo pour 238 Mio de RAM.
    # On tolere une marge pour l'overhead d'encodage multipart.
    max_request_bytes = MAX_IMAGE_ATTACHMENT_BYTES + 1 * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > max_request_bytes:
                return JSONResponse(
                    status_code=413,
                    content={"message": "Upload too large."},
                )
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"message": "Invalid Content-Length."},
            )
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
            return JSONResponse(
                status_code=400,
                content={"message": "No image file found in multipart upload."},
            )
    else:
        # Lecture PLAFONNEE en flux plutot que `await request.body()`, qui
        # bufferise tout sans borne : couvre le cas d'un corps `chunked` sans
        # Content-Length, qui echapperait a la garde ci-dessus.
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > max_request_bytes:
                return JSONResponse(
                    status_code=413,
                    content={"message": "Upload too large."},
                )
            chunks.append(chunk)
        content = b"".join(chunks)
    await data_store.upload_attachment_bytes(attachment_id, content, content_type)
    return Response(status_code=204)

# forward HTTP requests to the server
@app.post("/chatkit")
async def chatkit_endpoint(request: Request) -> Response:
    userId = request.headers.get(USER_ID_KEY)

    if userId is None:
        return JSONResponse(
            status_code=400,
            content={
                "message": "UserId Missing"
            }
        )

    # Model-provider choice travels per-request, set by the frontend's
    # settings panel (sessionStorage + custom fetch headers) -- no server-side
    # session state for it. Validated/defaulted in orchestrator.py, not here.
    provider = request.headers.get("X-Provider")
    api_key = request.headers.get("X-Provider-Api-Key")

    payload = await request.body()
    result = await server.process(
        payload,
        context={USER_ID_KEY: userId, "provider": provider, "api_key": api_key},
    )

    if isinstance(result, StreamingResult):
        return StreamingResponse(result, media_type="text/event-stream")
    if hasattr(result, "json"):
        return Response(content=result.json, media_type="application/json")

    return JSONResponse(result)
