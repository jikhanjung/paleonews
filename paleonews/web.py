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

from .config import load_config, apply_settings_overlay
from .db import Database

logger = logging.getLogger(__name__)

app = FastAPI(title="PaleoNews Admin")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_db: Database | None = None
_yaml_config: dict | None = None
_models_cache: tuple[float, list[dict]] | None = None
_MODELS_CACHE_TTL = 3600  # seconds

# Pipeline execution state
_pipeline_status = {"running": False, "last_result": None}


def get_db() -> Database:
    global _db
    if _db is None:
        config = get_config_yaml_only()
        _db = Database(config.get("db_path", "paleonews.db"))
        _db.init_tables()
    return _db


def get_config_yaml_only() -> dict:
    """Load yaml config only (no DB overlay). Used during DB initialization
    to avoid a chicken-and-egg loop."""
    global _yaml_config
    if _yaml_config is None:
        _yaml_config = load_config()
    return _yaml_config


def get_config() -> dict:
    """Return yaml config with current DB overrides overlaid.
    Re-overlays each call so UI changes are reflected immediately."""
    yaml_cfg = get_config_yaml_only()
    overrides = get_db().get_all_settings()
    return apply_settings_overlay(yaml_cfg, overrides)


def get_available_models() -> list[dict]:
    """Fetch the Anthropic model catalogue, cached for 1 hour. Returns
    [{"id": ..., "display_name": ...}, ...]. Empty on failure (network /
    missing API key) — UI then falls back to free-text input."""
    global _models_cache
    import time
    if _models_cache and time.time() - _models_cache[0] < _MODELS_CACHE_TTL:
        return _models_cache[1]
    try:
        from anthropic import Anthropic
        client = Anthropic()
        result = client.models.list(limit=50)
        models = [{"id": m.id, "display_name": m.display_name} for m in result.data]
        _models_cache = (time.time(), models)
        return models
    except Exception as e:
        logger.warning("Failed to fetch model catalogue: %s", e)
        return []


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
    telegram_chat_id: str = Form(""),
    name: str = Form(""),
    email: str = Form(""),
    is_admin: bool = Form(False),
):
    db = get_db()
    tg_id = telegram_chat_id.strip() or None
    if tg_id:
        existing = db.get_user_by_telegram_id(tg_id)
        if existing:
            return RedirectResponse("/users", status_code=303)
    db.add_user(telegram_chat_id=tg_id, username=name or None, is_admin=is_admin,
                 email=email or None)
    return RedirectResponse("/users", status_code=303)


@app.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(request: Request, user_id: int):
    db = get_db()
    user = db.get_user(user_id)
    if not user:
        return RedirectResponse("/users", status_code=303)
    if user["keywords"]:
        user["keywords_list"] = json.loads(user["keywords"])
    else:
        user["keywords_list"] = None
    user["memories"] = db.get_memories(user_id)
    dispatches = db.conn.execute(
        "SELECT d.* FROM dispatches d WHERE d.user_id = ? ORDER BY d.sent_at DESC LIMIT 20",
        (user_id,),
    ).fetchall()
    dispatches = [dict(r) for r in dispatches]
    return templates.TemplateResponse(request, "user_detail.html", {
        "user": user,
        "dispatches": dispatches,
    })


@app.post("/users/{user_id}/edit")
async def user_edit(
    user_id: int,
    telegram_chat_id: str = Form(""),
    username: str = Form(""),
    display_name: str = Form(""),
    email: str = Form(""),
    keywords: str = Form(""),
    is_active: bool = Form(False),
    is_admin: bool = Form(False),
    notify_telegram: bool = Form(False),
    notify_email: bool = Form(False),
):
    db = get_db()
    user = db.get_user(user_id)
    if not user:
        return RedirectResponse("/users", status_code=303)
    db.update_user(
        user_id,
        telegram_chat_id=telegram_chat_id.strip() or None,
        username=username.strip() or None,
        display_name=display_name.strip() or None,
        email=email.strip() or None,
        is_active=is_active,
        is_admin=is_admin,
        notify_telegram=notify_telegram,
        notify_email=notify_email,
    )
    kw = keywords.strip()
    if not kw or kw == "*":
        db.update_user_keywords(user_id, None)
    else:
        kw_list = [k.strip() for k in kw.split() if k.strip()]
        db.update_user_keywords(user_id, kw_list)
    return RedirectResponse(f"/users/{user_id}", status_code=303)


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
    feeds = get_db().get_all_feeds()
    available_models = get_available_models()
    return templates.TemplateResponse(request, "settings.html", {
        "config": config,
        "feeds": feeds,
        "available_models": available_models,
    })


@app.post("/settings/models/update")
async def settings_models_update(
    llm_provider: str = Form(...),
    filter_model: str = Form(...),
    summarizer_model: str = Form(...),
    chat_model: str = Form(...),
):
    db = get_db()
    db.set_setting("llm.provider", llm_provider.strip())
    db.set_setting("filter.llm_filter.model", filter_model.strip())
    db.set_setting("summarizer.model", summarizer_model.strip())
    db.set_setting("chat.model", chat_model.strip())
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/sources/add")
async def sources_add(url: str = Form(...)):
    import sqlite3
    url = url.strip()
    if url:
        try:
            get_db().add_feed(url)
        except sqlite3.IntegrityError:
            pass
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/sources/remove")
async def sources_remove(feed_id: int = Form(...)):
    get_db().remove_feed(feed_id)
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/sources/toggle")
async def sources_toggle(feed_id: int = Form(...), is_active: int = Form(...)):
    get_db().set_feed_active(feed_id, bool(is_active))
    return RedirectResponse("/settings", status_code=303)


def run_web(db: Database, config: dict, host: str = "0.0.0.0", port: int = 8000):
    """Start the web UI server."""
    import uvicorn
    global _db, _config
    _db = db
    _config = config
    print(f"웹 UI 시작: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
