

from chatkit.server import StreamingResult
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.data_store import USER_ID_KEY, MyDataStore
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
        content = await request.body()
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

    payload = await request.body()
    result = await server.process(payload, context={USER_ID_KEY: userId})

    if isinstance(result, StreamingResult):
        return StreamingResponse(result, media_type="text/event-stream")
    if hasattr(result, "json"):
        return Response(content=result.json, media_type="application/json")

    return JSONResponse(result)
