"""Telegram bot daemon for user self-service (subscribe, keywords, stop)."""

import json
import logging
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from .db import Database

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start — register or reactivate user."""
    db: Database = context.bot_data["db"]
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username
    display_name = update.effective_user.full_name

    existing = db.get_user_by_chat_id(chat_id)
    if existing:
        if not existing["is_active"]:
            db.update_user_active(existing["id"], True)
            await update.message.reply_text(
                "구독이 다시 활성화되었습니다!\n"
                "모든 고생물학 뉴스를 수신합니다.\n"
                "키워드를 설정하려면 /keywords 를 사용하세요."
            )
        else:
            await update.message.reply_text(
                "이미 구독 중입니다!\n"
                "키워드를 설정하려면 /keywords 를 사용하세요.\n"
                "구독을 해제하려면 /stop 을 사용하세요."
            )
    else:
        db.add_user(chat_id, username=username, display_name=display_name)
        await update.message.reply_text(
            "🦴 PaleoNews에 오신 것을 환영합니다!\n\n"
            "고생물학 뉴스 브리핑을 매일 받으실 수 있습니다.\n"
            "현재 모든 뉴스를 수신하도록 설정되어 있습니다.\n\n"
            "명령어:\n"
            "/keywords <단어1> <단어2> ... — 관심 키워드 설정\n"
            "/keywords — 현재 키워드 확인\n"
            "/keywords * — 전체 수신으로 변경\n"
            "/stop — 구독 해제"
        )
    logger.info("User %s (%s) started bot", chat_id, username)


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stop — deactivate user."""
    db: Database = context.bot_data["db"]
    chat_id = str(update.effective_chat.id)

    user = db.get_user_by_chat_id(chat_id)
    if user and user["is_active"]:
        db.update_user_active(user["id"], False)
        await update.message.reply_text(
            "구독이 해제되었습니다.\n"
            "다시 구독하려면 /start 를 사용하세요."
        )
        logger.info("User %s stopped bot", chat_id)
    else:
        await update.message.reply_text("현재 구독 중이 아닙니다. /start 로 구독하세요.")


async def cmd_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /keywords — view or set keywords."""
    db: Database = context.bot_data["db"]
    chat_id = str(update.effective_chat.id)

    user = db.get_user_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("먼저 /start 로 구독해주세요.")
        return

    args = context.args
    if not args:
        # Show current keywords
        kw = db.get_user_keywords(user["id"])
        if kw is None:
            await update.message.reply_text(
                "현재 설정: 전체 수신\n"
                "키워드를 설정하려면: /keywords dinosaur fossil mammoth"
            )
        else:
            await update.message.reply_text(
                f"현재 키워드: {', '.join(kw)}\n\n"
                "변경: /keywords <단어1> <단어2> ...\n"
                "전체 수신: /keywords *"
            )
    elif args == ["*"]:
        db.update_user_keywords(user["id"], None)
        await update.message.reply_text("전체 수신으로 변경되었습니다.")
        logger.info("User %s set keywords to all", chat_id)
    else:
        db.update_user_keywords(user["id"], args)
        await update.message.reply_text(
            f"키워드가 설정되었습니다: {', '.join(args)}\n"
            "해당 키워드가 포함된 뉴스만 수신합니다."
        )
        logger.info("User %s set keywords: %s", chat_id, args)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help — show available commands."""
    await update.message.reply_text(
        "🦴 PaleoNews Bot 명령어\n\n"
        "/start — 구독 시작\n"
        "/stop — 구독 해제\n"
        "/keywords — 현재 키워드 확인\n"
        "/keywords <단어1> <단어2> ... — 키워드 설정\n"
        "/keywords * — 전체 수신\n"
        "/help — 이 도움말"
    )


def run_bot(db: Database, config: dict):
    """Start the Telegram bot daemon."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        print("TELEGRAM_BOT_TOKEN 환경변수가 설정되지 않았습니다.")
        return

    # Seed admin if configured
    admin_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if admin_chat_id:
        db.seed_admin(admin_chat_id)

    app = Application.builder().token(bot_token).build()
    app.bot_data["db"] = db

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("keywords", cmd_keywords))
    app.add_handler(CommandHandler("help", cmd_help))

    print("Telegram 봇 시작... (Ctrl+C로 종료)")
    logger.info("Bot daemon started")
    app.run_polling()
