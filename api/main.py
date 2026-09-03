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


# ---------------------------------------------------------------
# Pages. Each one is a real route with its own URL and its own
# template — auth state is checked client-side by guard.js (see
# api/static/js/guard.js), which every authenticated page includes
# via base.html. /login is the only page without that guard.
# ---------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/", response_class=HTMLResponse)
async def query_page(request: Request):
    return templates.TemplateResponse("query.html", {"request": request, "active_page": "query"})


@app.get("/trace", response_class=HTMLResponse)
async def trace_page(request: Request):
    return templates.TemplateResponse("trace.html", {"request": request, "active_page": "trace"})


@app.get("/sources", response_class=HTMLResponse)
async def sources_page(request: Request):
    return templates.TemplateResponse("sources.html", {"request": request, "active_page": "sources"})


@app.get("/eval", response_class=HTMLResponse)
async def eval_page(request: Request):
    return templates.TemplateResponse("eval.html", {"request": request, "active_page": "eval"})


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request, "active_page": "admin"})


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
