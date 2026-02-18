import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import sys
from datetime import date
from pathlib import Path

from anthropic import Anthropic

from .config import load_config
from .db import Database
from .fetcher import fetch_all, load_sources
from .crawler import crawl_articles
from .filter import filter_articles, filter_articles_for_user
from .summarizer import generate_briefing, summarize_article
from .dispatcher.email import EmailDispatcher
from .dispatcher.telegram import TelegramDispatcher
from .dispatcher.webhook import WebhookDispatcher

logger = logging.getLogger("paleonews")


def setup_logging(config: dict):
    """Configure logging with console and optional file output."""
    log_config = config.get("logging", {})
    level_name = log_config.get("level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    # File handler (with rotation)
    log_file = log_config.get("file")
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        max_bytes = log_config.get("max_bytes", 5 * 1024 * 1024)  # 5MB
        backup_count = log_config.get("backup_count", 3)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)


def cmd_fetch(db: Database, config: dict) -> tuple[int, int]:
    sources = load_sources(config["sources_file"])
    articles = fetch_all(sources)
    new_count = db.save_articles(articles)
    print(f"수집: {len(articles)}건, 신규: {new_count}건")
    return len(articles), new_count


def cmd_filter(db: Database, config: dict) -> int:
    llm_enabled = config.get("filter", {}).get("llm_filter", {}).get("enabled", False)
    client = Anthropic() if llm_enabled else None
    relevant = filter_articles(db, config, llm_client=client)
    print(f"고생물학 관련: {relevant}건")
    return relevant


def cmd_crawl(db: Database, config: dict) -> int:
    max_crawl = config.get("crawler", {}).get("max_per_run", 20)
    crawled = crawl_articles(db, max_crawl=max_crawl)
    print(f"본문 크롤링: {crawled}건")
    return crawled


def cmd_summarize(db: Database, config: dict) -> int:
    unsummarized = db.get_unsummarized()
    if not unsummarized:
        print("요약할 기사가 없습니다.")
        return 0

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
    return len(targets)


def cmd_send(db: Database, config: dict):
    channels_config = config.get("channels", {})
    sent_any = False

    # Telegram — multi-user dispatch
    tg_config = channels_config.get("telegram", {})
    if tg_config.get("enabled", True):
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if bot_token:
            # Seed admin user if TELEGRAM_CHAT_ID is set
            admin_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
            if admin_chat_id:
                db.seed_admin(admin_chat_id)

            users = db.get_active_users()
            if not users and admin_chat_id:
                # Fallback: no users in DB yet, use env var directly
                users = [{"id": None, "chat_id": admin_chat_id, "keywords": None}]

            for user in users:
                user_id = user["id"]
                chat_id = user["chat_id"]

                if user_id is not None:
                    unsent = db.get_unsent_for_user("telegram", user_id)
                else:
                    unsent = db.get_unsent("telegram")

                if not unsent:
                    continue

                # Apply per-user keyword filter
                user_keywords = db.get_user_keywords(user_id) if user_id else None
                filtered = filter_articles_for_user(unsent, user_keywords)

                if not filtered:
                    # Mark as sent even if filtered out, to avoid re-processing
                    for a in unsent:
                        db.record_dispatch(a["id"], "telegram", "filtered", user_id=user_id)
                    continue

                briefing = generate_briefing(filtered, date.today().isoformat())
                dispatcher = TelegramDispatcher(bot_token, chat_id)
                success = asyncio.run(dispatcher.send_briefing(briefing))
                status = "success" if success else "failed"
                for a in filtered:
                    db.record_dispatch(a["id"], "telegram", status, user_id=user_id)
                # Mark non-filtered articles as filtered
                filtered_ids = {a["id"] for a in filtered}
                for a in unsent:
                    if a["id"] not in filtered_ids:
                        db.record_dispatch(a["id"], "telegram", "filtered", user_id=user_id)
                print(f"Telegram [{chat_id}] 전송 {'완료' if success else '실패'}: {len(filtered)}건")
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


def cmd_users(db: Database, args):
    """Manage users via CLI."""
    sub = args.users_command

    if sub == "list" or sub is None:
        users = db.get_all_users()
        if not users:
            print("등록된 사용자가 없습니다.")
            return
        print(f"사용자 ({len(users)}명):")
        for u in users:
            status = "활성" if u["is_active"] else "비활성"
            admin = " [관리자]" if u["is_admin"] else ""
            kw = u["keywords"]
            if kw:
                kw_list = json.loads(kw)
                kw_str = f" 키워드: {', '.join(kw_list)}"
            else:
                kw_str = " 키워드: 전체 수신"
            print(f"  {u['id']}. chat_id={u['chat_id']} ({status}{admin}){kw_str}")

    elif sub == "add":
        chat_id = args.chat_id
        existing = db.get_user_by_chat_id(chat_id)
        if existing:
            print(f"이미 등록된 사용자입니다: chat_id={chat_id}")
            return
        name = getattr(args, "name", None)
        is_admin = getattr(args, "admin", False)
        user_id = db.add_user(chat_id, username=name, is_admin=is_admin)
        print(f"사용자 추가: id={user_id}, chat_id={chat_id}")

    elif sub == "remove":
        chat_id = args.chat_id
        user = db.get_user_by_chat_id(chat_id)
        if not user:
            print(f"사용자를 찾을 수 없습니다: chat_id={chat_id}")
            return
        db.remove_user(user["id"])
        print(f"사용자 삭제: chat_id={chat_id}")

    elif sub == "keywords":
        chat_id = args.chat_id
        user = db.get_user_by_chat_id(chat_id)
        if not user:
            print(f"사용자를 찾을 수 없습니다: chat_id={chat_id}")
            return
        kw_input = getattr(args, "keywords_list", None)
        if kw_input is None or kw_input == []:
            # Show current keywords
            kw = db.get_user_keywords(user["id"])
            if kw is None:
                print(f"chat_id={chat_id}: 전체 수신")
            else:
                print(f"chat_id={chat_id}: {', '.join(kw)}")
        elif kw_input == ["*"]:
            db.update_user_keywords(user["id"], None)
            print(f"chat_id={chat_id}: 전체 수신으로 변경")
        else:
            db.update_user_keywords(user["id"], kw_input)
            print(f"chat_id={chat_id}: 키워드 설정 → {', '.join(kw_input)}")

    elif sub == "activate":
        chat_id = args.chat_id
        user = db.get_user_by_chat_id(chat_id)
        if not user:
            print(f"사용자를 찾을 수 없습니다: chat_id={chat_id}")
            return
        db.update_user_active(user["id"], True)
        print(f"사용자 활성화: chat_id={chat_id}")

    elif sub == "deactivate":
        chat_id = args.chat_id
        user = db.get_user_by_chat_id(chat_id)
        if not user:
            print(f"사용자를 찾을 수 없습니다: chat_id={chat_id}")
            return
        db.update_user_active(user["id"], False)
        print(f"사용자 비활성화: chat_id={chat_id}")


def cmd_sources(config: dict, args):
    sources_file = config["sources_file"]
    path = Path(sources_file)

    if args.sources_command == "list" or args.sources_command is None:
        if not path.exists():
            print(f"{sources_file}이 없습니다.")
            return
        sources = [line.strip() for line in path.read_text().strip().splitlines()
                   if line.strip() and not line.startswith("#")]
        print(f"피드 소스 ({len(sources)}개):")
        for i, url in enumerate(sources, 1):
            print(f"  {i}. {url}")

    elif args.sources_command == "add":
        url = args.url.strip()
        # Check for duplicates
        existing = []
        if path.exists():
            existing = [line.strip() for line in path.read_text().strip().splitlines()
                       if line.strip() and not line.startswith("#")]
        if url in existing:
            print(f"이미 등록된 소스입니다: {url}")
            return
        with open(path, "a") as f:
            f.write(f"\n{url}\n")
        print(f"소스 추가: {url}")

    elif args.sources_command == "remove":
        url = args.url.strip()
        if not path.exists():
            print(f"{sources_file}이 없습니다.")
            return
        lines = path.read_text().splitlines()
        new_lines = [line for line in lines if line.strip() != url]
        if len(new_lines) == len(lines):
            print(f"해당 소스를 찾을 수 없습니다: {url}")
            return
        path.write_text("\n".join(new_lines) + "\n")
        print(f"소스 삭제: {url}")


def cmd_status(db: Database, verbose: bool = False):
    stats = db.get_stats()
    print(f"전체 기사:   {stats['total']}건")
    print(f"관련 기사:   {stats['relevant']}건")
    print(f"요약 완료:   {stats['summarized']}건")
    print(f"전송 완료:   {stats['sent']}건")

    if not verbose:
        return

    # 출처별 통계
    source_stats = db.get_source_stats()
    if source_stats:
        print(f"\n--- 출처별 통계 ---")
        print(f"{'출처':<40} {'전체':>5} {'관련':>5} {'요약':>5}")
        print("-" * 58)
        for s in source_stats:
            name = (s["source"] or "Unknown")[:38]
            print(f"{name:<40} {s['total']:>5} {s['relevant']:>5} {s['summarized']:>5}")

    # 최근 실행 이력
    runs = db.get_recent_runs(5)
    if runs:
        print(f"\n--- 최근 실행 이력 ---")
        for r in runs:
            started = r["started_at"][:19].replace("T", " ")
            status = r["status"]
            print(
                f"  {started}  [{status}]  "
                f"수집:{r['fetched']} 신규:{r['new_articles']} "
                f"관련:{r['relevant']} 크롤:{r['crawled']} "
                f"요약:{r['summarized']} 전송:{r['sent']}"
            )
            if r.get("errors"):
                for err in r["errors"].split("\n"):
                    print(f"    ⚠ {err}")

    # 사용자 통계
    users = db.get_all_users()
    if users:
        active = sum(1 for u in users if u["is_active"])
        print(f"\n--- 사용자 ---")
        print(f"  전체: {len(users)}명, 활성: {active}명")


def main():
    parser = argparse.ArgumentParser(
        prog="paleonews",
        description="Paleontology news aggregator",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("run", help="Run full pipeline (fetch -> filter -> crawl -> summarize -> send)")
    subparsers.add_parser("fetch", help="Fetch RSS feeds only")
    subparsers.add_parser("filter", help="Filter articles only")
    subparsers.add_parser("crawl", help="Crawl article body text")
    subparsers.add_parser("summarize", help="Summarize articles only")
    subparsers.add_parser("send", help="Send briefing only")
    status_parser = subparsers.add_parser("status", help="Show database statistics")
    status_parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed stats")

    # Feed source management
    sources_parser = subparsers.add_parser("sources", help="Manage RSS feed sources")
    sources_sub = sources_parser.add_subparsers(dest="sources_command")
    sources_sub.add_parser("list", help="List all feed sources")
    add_parser = sources_sub.add_parser("add", help="Add a feed source")
    add_parser.add_argument("url", help="RSS feed URL to add")
    remove_parser = sources_sub.add_parser("remove", help="Remove a feed source")
    remove_parser.add_argument("url", help="RSS feed URL to remove")

    # User management
    users_parser = subparsers.add_parser("users", help="Manage subscribers")
    users_sub = users_parser.add_subparsers(dest="users_command")
    users_sub.add_parser("list", help="List all users")
    user_add = users_sub.add_parser("add", help="Add a user")
    user_add.add_argument("chat_id", help="Telegram chat ID")
    user_add.add_argument("--name", help="Username / display name")
    user_add.add_argument("--admin", action="store_true", help="Set as admin")
    user_remove = users_sub.add_parser("remove", help="Remove a user")
    user_remove.add_argument("chat_id", help="Telegram chat ID")
    user_kw = users_sub.add_parser("keywords", help="Set user keywords (use * for all)")
    user_kw.add_argument("chat_id", help="Telegram chat ID")
    user_kw.add_argument("keywords_list", nargs="*", help="Keywords (omit to show, * for all)")
    user_activate = users_sub.add_parser("activate", help="Activate a user")
    user_activate.add_argument("chat_id", help="Telegram chat ID")
    user_deactivate = users_sub.add_parser("deactivate", help="Deactivate a user")
    user_deactivate.add_argument("chat_id", help="Telegram chat ID")

    # Telegram bot daemon
    subparsers.add_parser("bot", help="Run Telegram bot daemon")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    config = load_config()
    setup_logging(config)
    db = Database(config.get("db_path", "paleonews.db"))
    db.init_tables()

    try:
        if args.command == "bot":
            from .bot import run_bot
            run_bot(db, config)
            return

        commands = {
            "fetch": lambda: cmd_fetch(db, config),
            "filter": lambda: cmd_filter(db, config),
            "crawl": lambda: cmd_crawl(db, config),
            "summarize": lambda: cmd_summarize(db, config),
            "send": lambda: cmd_send(db, config),
            "status": lambda: cmd_status(db, verbose=getattr(args, "verbose", False)),
            "sources": lambda: cmd_sources(config, args),
            "users": lambda: cmd_users(db, args),
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
    run_id = db.start_run()
    errors = []
    run_data = {"fetched": 0, "new_articles": 0, "relevant": 0, "crawled": 0, "summarized": 0, "sent": 0}

    print("=== 1/5 RSS 피드 수집 ===")
    try:
        fetched, new = cmd_fetch(db, config)
        run_data["fetched"] = fetched
        run_data["new_articles"] = new
    except Exception as e:
        logger.exception("Fetch failed")
        errors.append(f"수집 실패: {e}")

    print("\n=== 2/5 필터링 ===")
    try:
        run_data["relevant"] = cmd_filter(db, config)
    except Exception as e:
        logger.exception("Filter failed")
        errors.append(f"필터링 실패: {e}")

    print("\n=== 3/5 본문 크롤링 ===")
    try:
        run_data["crawled"] = cmd_crawl(db, config)
    except Exception as e:
        logger.exception("Crawl failed")
        errors.append(f"크롤링 실패: {e}")

    print("\n=== 4/5 한국어 요약 ===")
    try:
        run_data["summarized"] = cmd_summarize(db, config)
    except Exception as e:
        logger.exception("Summarize failed")
        errors.append(f"요약 실패: {e}")

    print("\n=== 5/5 전송 ===")
    try:
        cmd_send(db, config)
    except Exception as e:
        logger.exception("Send failed")
        errors.append(f"전송 실패: {e}")

    # Record sent count from dispatches
    stats = db.get_stats()
    run_data["sent"] = stats["sent"]

    print("\n=== 완료 ===")
    cmd_status(db)

    db.finish_run(run_id, errors=errors if errors else None, **run_data)

    if errors:
        print(f"\n⚠️ {len(errors)}건의 오류 발생")
        _notify_admin(config, errors)


if __name__ == "__main__":
    main()
