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
from .filter import filter_articles
from .summarizer import generate_briefing, summarize_article
from .dispatcher.telegram import TelegramDispatcher

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
    relevant = filter_articles(db, config)
    print(f"고생물학 관련: {relevant}건")


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
    unsent = db.get_unsent("telegram")
    if not unsent:
        print("전송할 기사가 없습니다.")
        return

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not bot_token or not chat_id:
        print("TELEGRAM_BOT_TOKEN 및 TELEGRAM_CHAT_ID 환경변수를 설정하세요.")
        sys.exit(1)

    briefing = generate_briefing(unsent, date.today().isoformat())
    dispatcher = TelegramDispatcher(bot_token, chat_id)

    success = asyncio.run(dispatcher.send_briefing(briefing))
    if success:
        for a in unsent:
            db.record_dispatch(a["id"], "telegram", "success")
        print(f"전송 완료: {len(unsent)}건")
    else:
        for a in unsent:
            db.record_dispatch(a["id"], "telegram", "failed")
        print("전송 실패")


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

    subparsers.add_parser("run", help="Run full pipeline (fetch → filter → summarize → send)")
    subparsers.add_parser("fetch", help="Fetch RSS feeds only")
    subparsers.add_parser("filter", help="Filter articles only")
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
            "summarize": lambda: cmd_summarize(db, config),
            "send": lambda: cmd_send(db, config),
            "status": lambda: cmd_status(db),
            "run": lambda: _run_pipeline(db, config),
        }
        commands[args.command]()
    finally:
        db.close()


def _run_pipeline(db: Database, config: dict):
    print("=== 1/4 RSS 피드 수집 ===")
    cmd_fetch(db, config)

    print("\n=== 2/4 필터링 ===")
    cmd_filter(db, config)

    print("\n=== 3/4 한국어 요약 ===")
    cmd_summarize(db, config)

    print("\n=== 4/4 Telegram 전송 ===")
    cmd_send(db, config)

    print("\n=== 완료 ===")
    cmd_status(db)


if __name__ == "__main__":
    main()
