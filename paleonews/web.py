"""FastAPI web UI for PaleoNews administration."""

import json
import logging
import os
import threading
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .config import load_config
from .db import Database

logger = logging.getLogger(__name__)

app = FastAPI(title="PaleoNews Admin")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_db: Database | None = None
_config: dict | None = None

# Pipeline execution state
_pipeline_status = {"running": False, "last_result": None}


def get_db() -> Database:
    global _db
    if _db is None:
        config = get_config()
        _db = Database(config.get("db_path", "paleonews.db"))
        _db.init_tables()
    return _db


def get_config() -> dict:
    global _config
    if _config is None:
        _config = load_config()
    return _config


# --- Dashboard ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    db = get_db()
    stats = db.get_stats()
    users = db.get_all_users()
    runs = db.get_recent_runs(5)
    source_stats = db.get_source_stats()
    active_users = sum(1 for u in users if u["is_active"])
    return templates.TemplateResponse(request, "dashboard.html", {
        "stats": stats,
        "users": users,
        "runs": runs,
        "active_users": active_users,
        "source_stats": source_stats,
        "pipeline_status": _pipeline_status,
    })


# --- Pipeline execution ---

@app.post("/pipeline/run")
async def pipeline_run():
    """Trigger pipeline execution in background thread."""
    if _pipeline_status["running"]:
        return JSONResponse({"status": "already_running"}, status_code=409)

    _pipeline_status["running"] = True
    _pipeline_status["last_result"] = None

    def run():
        try:
            from .__main__ import _run_pipeline
            config = get_config()
            db = Database(config.get("db_path", "paleonews.db"))
            db.init_tables()
            try:
                _run_pipeline(db, config)
                _pipeline_status["last_result"] = "success"
            finally:
                db.close()
        except Exception as e:
            logger.exception("Pipeline execution failed")
            _pipeline_status["last_result"] = f"error: {e}"
        finally:
            _pipeline_status["running"] = False

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return RedirectResponse("/", status_code=303)


@app.get("/pipeline/status")
async def pipeline_status():
    return JSONResponse(_pipeline_status)


# --- Articles ---

@app.get("/articles", response_class=HTMLResponse)
async def articles_list(
    request: Request,
    q: str = Query("", description="Search query"),
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=10, le=100),
    status: str = Query("all", description="Filter: all, relevant, summarized, sent"),
):
    db = get_db()
    articles, total = db.search_articles(q, status=status, page=page, per_page=per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(request, "articles.html", {
        "articles": articles,
        "q": q,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "status_filter": status,
    })


# --- Users ---

@app.get("/users", response_class=HTMLResponse)
async def users_list(request: Request):
    db = get_db()
    users = db.get_all_users()
    for u in users:
        if u["keywords"]:
            u["keywords_list"] = json.loads(u["keywords"])
        else:
            u["keywords_list"] = None
        u["memories"] = db.get_memories(u["id"])
    return templates.TemplateResponse(request, "users.html", {
        "users": users,
    })


@app.post("/users/add")
async def users_add(
    chat_id: str = Form(...),
    name: str = Form(""),
    email: str = Form(""),
    is_admin: bool = Form(False),
):
    db = get_db()
    existing = db.get_user_by_chat_id(chat_id)
    if not existing:
        db.add_user(chat_id, username=name or None, is_admin=is_admin,
                     email=email or None)
    return RedirectResponse("/users", status_code=303)


@app.post("/users/{user_id}/toggle")
async def users_toggle(user_id: int):
    db = get_db()
    user = db.get_user(user_id)
    if user:
        db.update_user_active(user_id, not user["is_active"])
    return RedirectResponse("/users", status_code=303)


@app.post("/users/{user_id}/keywords")
async def users_keywords(user_id: int, keywords: str = Form("")):
    db = get_db()
    kw = keywords.strip()
    if not kw or kw == "*":
        db.update_user_keywords(user_id, None)
    else:
        kw_list = [k.strip() for k in kw.split() if k.strip()]
        db.update_user_keywords(user_id, kw_list)
    return RedirectResponse("/users", status_code=303)


@app.post("/users/{user_id}/email")
async def users_email(user_id: int, email: str = Form("")):
    db = get_db()
    db.update_user_email(user_id, email.strip() or None)
    return RedirectResponse("/users", status_code=303)


@app.post("/users/{user_id}/delete")
async def users_delete(user_id: int):
    db = get_db()
    db.remove_user(user_id)
    return RedirectResponse("/users", status_code=303)


@app.post("/users/{user_id}/admin")
async def users_toggle_admin(user_id: int):
    db = get_db()
    user = db.get_user(user_id)
    if user:
        db.conn.execute(
            "UPDATE users SET is_admin = ? WHERE id = ?",
            (not user["is_admin"], user_id),
        )
        db.conn.commit()
    return RedirectResponse("/users", status_code=303)


# --- Settings ---

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    config = get_config()
    sources_file = config.get("sources_file", "sources.txt")
    sources = []
    path = Path(sources_file)
    if path.exists():
        sources = [line.strip() for line in path.read_text().splitlines()
                   if line.strip() and not line.startswith("#")]
    return templates.TemplateResponse(request, "settings.html", {
        "config": config,
        "sources": sources,
    })


@app.post("/settings/sources/add")
async def sources_add(url: str = Form(...)):
    config = get_config()
    path = Path(config.get("sources_file", "sources.txt"))
    existing = []
    if path.exists():
        existing = [line.strip() for line in path.read_text().splitlines()
                    if line.strip() and not line.startswith("#")]
    url = url.strip()
    if url and url not in existing:
        with open(path, "a") as f:
            f.write(f"{url}\n")
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/sources/remove")
async def sources_remove(url: str = Form(...)):
    config = get_config()
    path = Path(config.get("sources_file", "sources.txt"))
    if path.exists():
        lines = path.read_text().splitlines()
        new_lines = [line for line in lines if line.strip() != url.strip()]
        path.write_text("\n".join(new_lines) + "\n")
    return RedirectResponse("/settings", status_code=303)


def run_web(db: Database, config: dict, host: str = "0.0.0.0", port: int = 8000):
    """Start the web UI server."""
    import uvicorn
    global _db, _config
    _db = db
    _config = config
    print(f"웹 UI 시작: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
