"""로그에서 자격증명을 가린다.

python-telegram-bot 은 httpx 를 쓰고, httpx 의 INFO 로거는 요청 URL 을 통째로 찍는다.
Telegram API 는 토큰을 **경로에** 담기 때문에 그대로 두면 로그에 이렇게 남는다:

    httpx: HTTP Request: POST https://api.telegram.org/bot123456:AAH.../getUpdates "200 OK"

이 로그를 읽을 수 있는 사람은 봇을 그대로 조종할 수 있다. 토큰은 그 자체가
인증 수단이라 "민감한가"가 아니라 "그대로 제시하면 통과하는가"가 판단 기준이다.

핸들러에 붙이므로 로거 이름과 무관하게 콘솔·파일로 나가는 모든 레코드에 적용된다.
"""
import logging
import re

# 1) Telegram: 경로에 담긴 봇 토큰  .../bot<숫자>:<영숫자_-> /...
_TELEGRAM_TOKEN = re.compile(r"(/bot)(\d{6,})(:[A-Za-z0-9_-]{20,})")

# 2) 쿼리스트링에 담긴 흔한 비밀값들 (api_key=, token=, access_token=, key=, secret=)
_QUERY_SECRET = re.compile(
    r"([?&](?:api[_-]?key|access[_-]?token|token|secret|key)=)([^&\s\"']+)",
    re.IGNORECASE,
)

# 3) Authorization 헤더가 문자열로 찍히는 경우
_BEARER = re.compile(r"(Bearer\s+)([A-Za-z0-9._\-]{10,})", re.IGNORECASE)


def redact(text: str) -> str:
    """문자열에서 자격증명을 가린다. 어디를 가렸는지는 남긴다(디버깅용)."""
    if not text:
        return text
    # 봇 ID 는 남기고 토큰 본문만 가린다 — 어느 봇인지는 알아야 추적이 되고,
    # ID 만으로는 API 를 호출할 수 없다.
    text = _TELEGRAM_TOKEN.sub(r"\1\2:<redacted>", text)
    text = _QUERY_SECRET.sub(r"\1<redacted>", text)
    text = _BEARER.sub(r"\1<redacted>", text)
    return text


class RedactingFilter(logging.Filter):
    """포맷된 메시지를 가린 뒤 레코드를 통과시킨다.

    args 를 남겨두면 포맷 단계에서 원문이 되살아나므로, 미리 포맷해서 msg 에 넣고
    args 를 비운다. exc_info 의 트레이스백 본문까지는 건드리지 않는다 —
    예외 메시지에 토큰이 실릴 수 있다면 그건 별도로 다룰 문제다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True  # 포맷 실패는 여기서 삼키지 않는다
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True
