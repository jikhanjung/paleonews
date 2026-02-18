import argparse
import asyncio
import logging
import os
import sys
from datetime import date

from anthropic import Anthropic

from .config import load_config
from .db import Database
from .fetcher import fetch_all, load_sources
from .crawler import crawl_articles
from .filter import filter_articles
from .summarizer import generate_briefing, summarize_article
from .dispatcher.email import EmailDispatcher
from .dispatcher.telegram import TelegramDispatcher
from .dispatcher.webhook import WebhookDispatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("paleonews")


def cmd_fetch(db: Database, config: dict):
    sources = load_sources(config["sources_file"])
    articles = fetch_all(sources)
    new_count = db.save_articles(articles)
    print(f"수집: {len(articles)}건, 신규: {new_count}건")


def cmd_filter(db: Database, config: dict):
    llm_enabled = config.get("filter", {}).get("llm_filter", {}).get("enabled", False)
    client = Anthropic() if llm_enabled else None
    relevant = filter_articles(db, config, llm_client=client)
    print(f"고생물학 관련: {relevant}건")


def cmd_crawl(db: Database, config: dict):
    max_crawl = config.get("crawler", {}).get("max_per_run", 20)
    crawled = crawl_articles(db, max_crawl=max_crawl)
    print(f"본문 크롤링: {crawled}건")


def cmd_summarize(db: Database, config: dict):
    unsummarized = db.get_unsummarized()
    if not unsummarized:
        print("요약할 기사가 없습니다.")
        return

    model = config.get("summarizer", {}).get("model", "claude-sonnet-4-20250514")
    max_articles = config.get("summarizer", {}).get("max_articles_per_run", 20)
    client = Anthropic()

    targets = unsummarized[:max_articles]
    for i, article in enumerate(targets, 1):
        print(f"요약 중... ({i}/{len(targets)}) {article['title'][:60]}")
        try:
            title_ko, summary_ko = summarize_article(client, article, model)
            db.save_summary(article["id"], title_ko, summary_ko)
        except Exception:
            logger.exception("Failed to summarize article %d", article["id"])

    print(f"요약 완료: {len(targets)}건")


def cmd_send(db: Database, config: dict):
    channels_config = config.get("channels", {})
    sent_any = False

    # Telegram
    tg_config = channels_config.get("telegram", {})
    if tg_config.get("enabled", True):
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if bot_token and chat_id:
            unsent = db.get_unsent("telegram")
            if unsent:
                briefing = generate_briefing(unsent, date.today().isoformat())
                dispatcher = TelegramDispatcher(bot_token, chat_id)
                success = asyncio.run(dispatcher.send_briefing(briefing))
                status = "success" if success else "failed"
                for a in unsent:
                    db.record_dispatch(a["id"], "telegram", status)
                print(f"Telegram 전송 {'완료' if success else '실패'}: {len(unsent)}건")
                sent_any = True

    # Email
    email_config = channels_config.get("email", {})
    if email_config.get("enabled", False):
        password = os.environ.get("EMAIL_PASSWORD", "")
        sender = email_config.get("sender", "")
        recipients = email_config.get("recipients", [])
        if sender and password and recipients:
            unsent = db.get_unsent("email")
            if unsent:
                briefing = generate_briefing(unsent, date.today().isoformat())
                dispatcher = EmailDispatcher(
                    email_config.get("smtp_host", "smtp.gmail.com"),
                    email_config.get("smtp_port", 587),
                    sender, password, recipients,
                )
                success = asyncio.run(dispatcher.send_briefing(briefing))
                status = "success" if success else "failed"
                for a in unsent:
                    db.record_dispatch(a["id"], "email", status)
                print(f"Email 전송 {'완료' if success else '실패'}: {len(unsent)}건")
                sent_any = True

    # Slack
    slack_config = channels_config.get("slack", {})
    if slack_config.get("enabled", False):
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
        if webhook_url:
            unsent = db.get_unsent("slack")
            if unsent:
                briefing = generate_briefing(unsent, date.today().isoformat())
                dispatcher = WebhookDispatcher(webhook_url, "slack")
                success = asyncio.run(dispatcher.send_briefing(briefing))
                status = "success" if success else "failed"
                for a in unsent:
                    db.record_dispatch(a["id"], "slack", status)
                print(f"Slack 전송 {'완료' if success else '실패'}: {len(unsent)}건")
                sent_any = True

    # Discord
    discord_config = channels_config.get("discord", {})
    if discord_config.get("enabled", False):
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
        if webhook_url:
            unsent = db.get_unsent("discord")
            if unsent:
                briefing = generate_briefing(unsent, date.today().isoformat())
                dispatcher = WebhookDispatcher(webhook_url, "discord")
                success = asyncio.run(dispatcher.send_briefing(briefing))
                status = "success" if success else "failed"
                for a in unsent:
                    db.record_dispatch(a["id"], "discord", status)
                print(f"Discord 전송 {'완료' if success else '실패'}: {len(unsent)}건")
                sent_any = True

    if not sent_any:
        print("전송할 기사가 없거나 활성화된 채널이 없습니다.")


def cmd_status(db: Database):
    stats = db.get_stats()
    print(f"전체 기사:   {stats['total']}건")
    print(f"관련 기사:   {stats['relevant']}건")
    print(f"요약 완료:   {stats['summarized']}건")
    print(f"전송 완료:   {stats['sent']}건")


def main():
    parser = argparse.ArgumentParser(
        prog="paleonews",
        description="Paleontology news aggregator",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("run", help="Run full pipeline (fetch → filter → crawl → summarize → send)")
    subparsers.add_parser("fetch", help="Fetch RSS feeds only")
    subparsers.add_parser("filter", help="Filter articles only")
    subparsers.add_parser("crawl", help="Crawl article body text")
    subparsers.add_parser("summarize", help="Summarize articles only")
    subparsers.add_parser("send", help="Send briefing only")
    subparsers.add_parser("status", help="Show database statistics")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    config = load_config()
    db = Database(config.get("db_path", "paleonews.db"))
    db.init_tables()

    try:
        commands = {
            "fetch": lambda: cmd_fetch(db, config),
            "filter": lambda: cmd_filter(db, config),
            "crawl": lambda: cmd_crawl(db, config),
            "summarize": lambda: cmd_summarize(db, config),
            "send": lambda: cmd_send(db, config),
            "status": lambda: cmd_status(db),
            "run": lambda: _run_pipeline(db, config),
        }
        commands[args.command]()
    finally:
        db.close()


def _notify_admin(config: dict, errors: list[str]):
    """Send error notification to admin via Telegram."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    admin_chat_id = os.environ.get("ADMIN_CHAT_ID", "") or os.environ.get("TELEGRAM_CHAT_ID", "")

    if not bot_token or not admin_chat_id:
        return

    message = "⚠️ PaleoNews 파이프라인 오류\n\n" + "\n".join(f"• {e}" for e in errors)
    dispatcher = TelegramDispatcher(bot_token, admin_chat_id)
    try:
        asyncio.run(dispatcher.send_briefing(message))
    except Exception:
        logger.exception("Failed to send error notification")


def _run_pipeline(db: Database, config: dict):
    errors = []

    print("=== 1/5 RSS 피드 수집 ===")
    try:
        cmd_fetch(db, config)
    except Exception as e:
        logger.exception("Fetch failed")
        errors.append(f"수집 실패: {e}")

    print("\n=== 2/5 필터링 ===")
    try:
        cmd_filter(db, config)
    except Exception as e:
        logger.exception("Filter failed")
        errors.append(f"필터링 실패: {e}")

    print("\n=== 3/5 본문 크롤링 ===")
    try:
        cmd_crawl(db, config)
    except Exception as e:
        logger.exception("Crawl failed")
        errors.append(f"크롤링 실패: {e}")

    print("\n=== 4/5 한국어 요약 ===")
    try:
        cmd_summarize(db, config)
    except Exception as e:
        logger.exception("Summarize failed")
        errors.append(f"요약 실패: {e}")

    print("\n=== 5/5 전송 ===")
    try:
        cmd_send(db, config)
    except Exception as e:
        logger.exception("Send failed")
        errors.append(f"전송 실패: {e}")

    print("\n=== 완료 ===")
    cmd_status(db)

    if errors:
        print(f"\n⚠️ {len(errors)}건의 오류 발생")
        _notify_admin(config, errors)


if __name__ == "__main__":
    main()
