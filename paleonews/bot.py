"""Telegram bot daemon for user self-service and chat."""

import json
import logging
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .db import Database
from .llm import create_llm_client, LLMClient

logger = logging.getLogger(__name__)

CHAT_SYSTEM_PROMPT = """\
당신은 고생물학(paleontology) 전문 AI 어시스턴트입니다.
사용자와 친근하게 대화하며, 고생물학 관련 질문에 전문적으로 답변합니다.
한국어로 답변하되, 학술 용어는 영어를 병기할 수 있습니다.
답변은 간결하게 하되, 필요한 정보는 빠뜨리지 마세요.

{memory_section}

사용자가 무언가를 "기억해줘", "기억해", "remember" 등으로 요청하면,
반드시 응답의 맨 마지막 줄에 다음 형식으로 기억할 내용을 추가하세요:
[MEMORY: 기억할 내용]

사용자가 "잊어줘", "잊어", "forget" 등으로 기억 삭제를 요청하면,
응답의 맨 마지막 줄에 다음 형식으로 표시하세요:
[FORGET: 삭제할 내용의 키워드]"""


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
            "/memories — 저장된 기억 확인\n"
            "/forget — 기억 전체 삭제\n"
            "/stop — 구독 해제\n\n"
            "자유롭게 메시지를 보내면 대화할 수 있습니다!"
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


async def cmd_memories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /memories — show saved memories."""
    db: Database = context.bot_data["db"]
    chat_id = str(update.effective_chat.id)

    user = db.get_user_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("먼저 /start 로 구독해주세요.")
        return

    memories = db.get_memories(user["id"])
    if not memories:
        await update.message.reply_text("저장된 기억이 없습니다.")
        return

    lines = ["📝 저장된 기억 목록:\n"]
    for i, m in enumerate(memories, 1):
        lines.append(f"{i}. {m['content']}")
    lines.append("\n기억을 모두 삭제하려면 /forget 을 사용하세요.")
    await update.message.reply_text("\n".join(lines))


async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /forget — clear all memories."""
    db: Database = context.bot_data["db"]
    chat_id = str(update.effective_chat.id)

    user = db.get_user_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("먼저 /start 로 구독해주세요.")
        return

    db.clear_memories(user["id"])
    await update.message.reply_text("모든 기억이 삭제되었습니다.")
    logger.info("User %s cleared memories", chat_id)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help — show available commands."""
    await update.message.reply_text(
        "🦴 PaleoNews Bot 명령어\n\n"
        "/start — 구독 시작\n"
        "/stop — 구독 해제\n"
        "/keywords — 현재 키워드 확인\n"
        "/keywords <단어1> <단어2> ... — 키워드 설정\n"
        "/keywords * — 전체 수신\n"
        "/memories — 저장된 기억 확인\n"
        "/forget — 기억 전체 삭제\n"
        "/help — 이 도움말\n\n"
        "자유롭게 메시지를 보내면 대화할 수 있습니다!"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text messages — chat with Claude."""
    db: Database = context.bot_data["db"]
    llm: LLMClient = context.bot_data["llm"]
    chat_model: str = context.bot_data["chat_model"]
    chat_id = str(update.effective_chat.id)
    user_text = update.message.text

    # Auto-register if not a user
    user = db.get_user_by_chat_id(chat_id)
    if not user:
        username = update.effective_user.username
        display_name = update.effective_user.full_name
        db.add_user(chat_id, username=username, display_name=display_name)
        user = db.get_user_by_chat_id(chat_id)

    # Build memory context
    memories = db.get_memories(user["id"])
    if memories:
        memory_lines = "\n".join(f"- {m['content']}" for m in memories)
        memory_section = f"이 사용자에 대해 기억하고 있는 내용:\n{memory_lines}"
    else:
        memory_section = ""

    system = CHAT_SYSTEM_PROMPT.format(memory_section=memory_section)

    # Send typing indicator
    await update.effective_chat.send_action("typing")

    try:
        response = llm.chat(chat_model, user_text, system=system, max_tokens=1024)
    except Exception as e:
        logger.error("Chat LLM error for user %s: %s", chat_id, e)
        await update.message.reply_text("죄송합니다, 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
        return

    # Process memory commands in response
    reply = response
    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("[MEMORY:") and line.endswith("]"):
            memory_content = line[8:-1].strip()
            if memory_content:
                db.save_memory(user["id"], memory_content)
                logger.info("Saved memory for user %s: %s", chat_id, memory_content)
            reply = reply.replace(line, "").strip()
        elif line.startswith("[FORGET:") and line.endswith("]"):
            forget_keyword = line[8:-1].strip().lower()
            if forget_keyword:
                for m in memories:
                    if forget_keyword in m["content"].lower():
                        db.delete_memory(m["id"])
                        logger.info("Deleted memory %d for user %s", m["id"], chat_id)
            reply = reply.replace(line, "").strip()

    if reply:
        await update.message.reply_text(reply)


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

    # Initialize LLM client for chat
    llm = create_llm_client(config)
    chat_model = config.get("chat", {}).get("model", "claude-haiku-4-5-20251001")

    app = Application.builder().token(bot_token).build()
    app.bot_data["db"] = db
    app.bot_data["llm"] = llm
    app.bot_data["chat_model"] = chat_model

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("keywords", cmd_keywords))
    app.add_handler(CommandHandler("memories", cmd_memories))
    app.add_handler(CommandHandler("forget", cmd_forget))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Telegram 봇 시작... (Ctrl+C로 종료)")
    logger.info("Bot daemon started with chat model: %s", chat_model)
    app.run_polling()
