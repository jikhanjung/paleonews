import logging
import re

from .llm import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "당신은 고생물학 전문 과학 저널리스트입니다. 영문 과학 기사를 한국어로 정확하고 자연스럽게 요약합니다."

ARTICLE_PROMPT = """\
아래 영문 기사를 한국어로 요약해주세요.

제목: {title}
요약: {summary}
출처: {source}

다음 형식으로 정확히 답변하세요:
제목: (한국어 제목, 30자 이내)
요약: (핵심 내용 2~3문장, 이 연구/발견이 왜 중요한지 포함)"""

ARTICLE_PROMPT_WITH_BODY = """\
아래 영문 기사를 한국어로 요약해주세요.

제목: {title}
본문: {body}
출처: {source}

다음 형식으로 정확히 답변하세요:
제목: (한국어 제목, 30자 이내)
요약: (핵심 내용 3~4문장, 이 연구/발견이 왜 중요한지 포함)"""


def summarize_article(
    client: LLMClient, article: dict, model: str
) -> tuple[str, str]:
    """Summarize a single article. Returns (title_ko, summary_ko)."""
    body = article.get("body")
    if body and len(body) >= 100:
        prompt = ARTICLE_PROMPT_WITH_BODY.format(
            title=article.get("title", ""),
            body=body,
            source=article.get("source", ""),
        )
    else:
        prompt = ARTICLE_PROMPT.format(
            title=article.get("title", ""),
            summary=article.get("summary", ""),
            source=article.get("source", ""),
        )

    text = client.chat(model, prompt, system=SYSTEM_PROMPT, max_tokens=512)
    return _parse_summary(text)


def _parse_summary(text: str) -> tuple[str, str]:
    """Parse LLM response into (title_ko, summary_ko)."""
    title_ko = ""
    summary_ko = ""

    title_match = re.search(r"제목:\s*(.+)", text)
    if title_match:
        title_ko = title_match.group(1).strip()

    summary_match = re.search(r"요약:\s*(.+)", text, re.DOTALL)
    if summary_match:
        summary_ko = summary_match.group(1).strip()

    # Fallback: if parsing fails, use the whole text as summary
    if not title_ko and not summary_ko:
        summary_ko = text

    return title_ko, summary_ko


def generate_briefing(articles: list[dict], date: str) -> str:
    """Compose a daily briefing text from summarized articles."""
    lines = [
        f"🦴 고생물학 뉴스 브리핑 ({date})",
        "━" * 22,
        "",
    ]

    for i, a in enumerate(articles):
        lines.append(f"📌 {a.get('title_ko', a.get('title', ''))}")
        lines.append(a.get("summary_ko", ""))
        lines.append(f"🔗 원문: {a.get('url', '')}")
        lines.append(f"📰 출처: {a.get('source', '')}")
        if i < len(articles) - 1:
            lines.append("")
            lines.append("─" * 22)
            lines.append("")

    lines.append("")
    lines.append("━" * 22)
    lines.append(f"총 {len(articles)}건의 뉴스가 수집되었습니다.")

    return "\n".join(lines)
