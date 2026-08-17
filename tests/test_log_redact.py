import io
import logging

from paleonews.log_redact import RedactingFilter, redact

# 실제로 운영 로그에 10만 건 넘게 남아 있던 형태 (토큰 본문은 더미로 교체).
REAL_LINE = (
    'HTTP Request: POST '
    'https://api.telegram.org/bot8042989190:AAH_dummyTOKENvalue_1234567890/getUpdates '
    '"HTTP/1.1 200 OK"'
)
TOKEN_BODY = "AAH_dummyTOKENvalue_1234567890"


def test_telegram_path_token_is_redacted():
    out = redact(REAL_LINE)
    assert TOKEN_BODY not in out
    # 봇 ID 는 남긴다 — 어느 봇인지 추적은 되어야 하고, ID 만으로는 API 를 부를 수 없다.
    assert "bot8042989190:<redacted>" in out


def test_telegram_file_download_url_is_redacted():
    out = redact(f"GET https://api.telegram.org/file/bot8042989190:{TOKEN_BODY}/photo.jpg")
    assert TOKEN_BODY not in out


def test_query_string_secrets_are_redacted():
    for url in (
        "https://example.com/v1?api_key=sk-abcdefghijklmnop&x=1",
        "https://example.com/cb?access_token=ya29.aBcDeFgHiJkLmNoP",
        "https://example.com/x?token=abcdef123456&y=2",
    ):
        out = redact(url)
        assert "<redacted>" in out
        assert "sk-abcdefghijklmnop" not in out
        assert "ya29.aBcDeFgHiJkLmNoP" not in out
        assert "abcdef123456" not in out
    # 가려도 나머지 쿼리 파라미터는 살아 있어야 로그가 쓸모를 유지한다.
    assert "&x=1" in redact("https://example.com/v1?api_key=sk-abcdefghijklmnop&x=1")


def test_bearer_header_is_redacted():
    out = redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig")
    assert "eyJhbGciOiJIUzI1NiJ9.payload.sig" not in out


def test_ordinary_text_is_untouched():
    msg = "Imported 12 feeds from sources.txt"
    assert redact(msg) == msg


def _capture(logger_name, msg, *args):
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    saved, saved_level = root.handlers, root.level
    root.handlers = [handler]
    # ⚠️ `root.level = ...` 직접 대입은 안 된다 — 파이썬 logging 은 로거별로 "이 레벨이 켜졌나"를
    # 캐시하고(Logger._cache), 그 캐시는 **setLevel() 이 호출하는 manager._clear_cache() 로만** 지워진다.
    # 직접 대입하면 캐시가 남아, 앞선 테스트에서 이미 한 번 로깅된 적 있는 로거(예: TestClient 가
    # 내부적으로 httpx 를 쓰면서 캐시를 채운 경우)는 INFO 가 꺼진 것으로 판정돼 레코드가 통째로 버려진다.
    root.setLevel(logging.INFO)
    try:
        logging.getLogger(logger_name).info(msg, *args)
    finally:
        root.handlers = saved
        root.setLevel(saved_level)
    return buf.getvalue()


def test_filter_applies_to_third_party_logger_with_lazy_args():
    """httpx 는 %s 인자로 로깅한다 — args 를 비우지 않으면 포맷 단계에서 원문이 되살아난다."""
    out = _capture(
        "httpx",
        'HTTP Request: %s %s "%s"',
        "POST",
        f"https://api.telegram.org/bot8042989190:{TOKEN_BODY}/getUpdates",
        "HTTP/1.1 200 OK",
    )
    assert TOKEN_BODY not in out
    assert "bot8042989190:<redacted>" in out


def test_filter_keeps_normal_records_formatted():
    out = _capture("paleonews", "Imported %d feeds", 3)
    assert "Imported 3 feeds" in out


# --- Django 로깅 설정에도 붙어 있는가 (0.3.7 회귀) --------------------------

def test_django_logging_attaches_redactor_to_every_handler():
    """`manage.py bot`·gunicorn 은 Django LOGGING 을 쓴다 — 여기 빠지면 마스킹이 통째로 사라진다.

    회귀(0.3.7): FastAPI→Django 전환 때 Django LOGGING 이 CLI 의 `setup_logging()` 을 밀어내,
    배포 직후 봇 폴링 로그에 텔레그램 토큰이 **다시 평문으로** 찍혔다.
    """
    from config import settings as dj

    assert "redact" in dj.LOGGING.get("filters", {}), "LOGGING 에 redact 필터가 없다"
    assert dj.LOGGING["filters"]["redact"]["()"].endswith("RedactingFilter")
    handlers = dj.LOGGING["handlers"]
    assert handlers, "핸들러가 하나도 없다"
    for name, handler in handlers.items():
        assert "redact" in handler.get("filters", []), f"핸들러 '{name}' 에 redact 가 안 붙었다"


def test_django_logging_config_actually_redacts():
    """설정을 실제로 적용해 httpx 레코드가 마스킹되는지 본다(선언만으로는 부족하다)."""
    import io
    import logging.config

    from config import settings as dj

    buf = io.StringIO()
    config = {**dj.LOGGING,
              "handlers": {"console": {**dj.LOGGING["handlers"]["console"],
                                       "class": "logging.StreamHandler",
                                       "stream": buf}}}
    saved = logging.getLogger().handlers, logging.getLogger().level
    try:
        logging.config.dictConfig(config)
        logging.getLogger("httpx").info(
            'HTTP Request: %s %s "%s"', "POST",
            f"https://api.telegram.org/bot8042989190:{TOKEN_BODY}/getUpdates", "HTTP/1.1 200 OK")
    finally:
        logging.getLogger().handlers, _ = saved
        logging.getLogger().setLevel(saved[1])

    out = buf.getvalue()
    assert TOKEN_BODY not in out
    assert "bot8042989190:<redacted>" in out
