from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api.routes import departments, documents, ingest, query, traces
from config.settings import settings
from exception.exceptions import AppError
from exception.handlers import app_error_handler, unhandled_error_handler

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Pharma RAG API", version="1.0.0")

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.include_router(query.router, prefix="/api")
app.include_router(ingest.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(traces.router, prefix="/api")
app.include_router(departments.router, prefix="/api")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/config.js", response_class=PlainTextResponse)
async def config_js():
    # Public, browser-safe values only — the anon key has no power beyond
    # what RLS allows. Never serve the service-role key from here.
    js = (
        "window.APP_CONFIG = {\n"
        f'  SUPABASE_URL: "{settings.supabase_url}",\n'
        f'  SUPABASE_ANON_KEY: "{settings.supabase_anon_key}",\n'
        "};\n"
    )
    return PlainTextResponse(content=js, media_type="application/javascript")


@app.get("/health")
async def health():
    return {"status": "ok"}
