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
    root.handlers, root.level = [handler], logging.INFO
    try:
        logging.getLogger(logger_name).info(msg, *args)
    finally:
        root.handlers, root.level = saved, saved_level
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
