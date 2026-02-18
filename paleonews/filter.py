import logging
import re

from anthropic import Anthropic

logger = logging.getLogger(__name__)

LLM_FILTER_PROMPT = """\
다음 기사가 고생물학(paleontology)과 직접 관련이 있는지 판단해주세요.
고생물학: 화석, 멸종 생물, 지질시대 생물, 고인류학, 진화 고생물학 등

제목: {title}
요약: {summary}

"yes" 또는 "no"로만 답변하세요."""


def is_dedicated_feed(feed_url: str, patterns: list[str]) -> bool:
    """Check if feed_url matches any dedicated feed pattern."""
    feed_lower = feed_url.lower()
    return any(p.lower() in feed_lower for p in patterns)


def keyword_match(title: str, summary: str, keywords: list[str]) -> bool:
    """Return True if any keyword appears in title or summary (prefix matching, case-insensitive)."""
    text = f"{title} {summary}".lower()
    return any(re.search(rf"\b{re.escape(kw.lower())}", text) for kw in keywords)


def llm_filter(client: Anthropic, article: dict, model: str) -> bool:
    """Use LLM to judge paleontology relevance. Returns True if relevant."""
    prompt = LLM_FILTER_PROMPT.format(
        title=article.get("title", ""),
        summary=article.get("summary", ""),
    )
    try:
        response = client.messages.create(
            model=model,
            max_tokens=8,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = response.content[0].text.strip().lower()
        return answer.startswith("yes")
    except Exception:
        logger.exception("LLM filter failed for article %s", article.get("id"))
        # On failure, keep the article (conservative approach)
        return True


def filter_articles(db, config: dict, llm_client: Anthropic | None = None) -> int:
    """Filter unfiltered articles and update DB. Returns count of relevant articles."""
    dedicated = config.get("dedicated_feeds", [])
    keywords = config.get("filter", {}).get("keywords", [])
    llm_config = config.get("filter", {}).get("llm_filter", {})
    llm_enabled = llm_config.get("enabled", False) and llm_client is not None
    llm_model = llm_config.get("model", "claude-haiku-4-5-20251001")

    unfiltered = db.get_unfiltered()
    relevant_count = 0
    llm_checked = 0

    for article in unfiltered:
        feed_url = article.get("feed_url", "") or ""

        if is_dedicated_feed(feed_url, dedicated):
            is_relevant = True
        else:
            title = article.get("title", "") or ""
            summary = article.get("summary", "") or ""
            is_relevant = keyword_match(title, summary, keywords)

            # LLM 2차 필터: 키워드 매칭된 비전용 피드 기사만 검증
            if is_relevant and llm_enabled:
                is_relevant = llm_filter(llm_client, article, llm_model)
                llm_checked += 1

        db.mark_relevant(article["id"], is_relevant)
        if is_relevant:
            relevant_count += 1

    logger.info(
        "Filtered %d articles: %d relevant, %d irrelevant (LLM checked: %d)",
        len(unfiltered), relevant_count, len(unfiltered) - relevant_count, llm_checked,
    )
    return relevant_count
