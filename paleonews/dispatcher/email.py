import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .base import BaseDispatcher

logger = logging.getLogger(__name__)

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:20px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;">
  <!-- Header -->
  <tr><td style="background:#2c3e50;padding:24px 30px;">
    <h1 style="margin:0;color:#fff;font-size:20px;">🦴 고생물학 뉴스 브리핑</h1>
    <p style="margin:6px 0 0;color:#bdc3c7;font-size:13px;">{date}</p>
  </td></tr>
  <!-- Body -->
  <tr><td style="padding:20px 30px;">
    {articles_html}
  </td></tr>
  <!-- Footer -->
  <tr><td style="background:#ecf0f1;padding:16px 30px;text-align:center;">
    <p style="margin:0;color:#7f8c8d;font-size:12px;">
      총 {count}건의 뉴스가 수집되었습니다. | PaleoNews
    </p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""

ARTICLE_HTML = """\
<div style="margin-bottom:20px;padding-bottom:20px;border-bottom:1px solid #eee;">
  <h2 style="margin:0 0 8px;font-size:16px;color:#2c3e50;">{title_ko}</h2>
  <p style="margin:0 0 10px;color:#555;font-size:14px;line-height:1.6;">{summary_ko}</p>
  <p style="margin:0;font-size:12px;color:#7f8c8d;">
    📰 {source} &nbsp;|&nbsp;
    <a href="{url}" style="color:#3498db;text-decoration:none;">원문 보기 →</a>
  </p>
</div>"""


class EmailDispatcher(BaseDispatcher):
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        sender: str,
        password: str,
        recipients: list[str],
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.sender = sender
        self.password = password
        self.recipients = recipients

    async def send_briefing(self, briefing: str) -> bool:
        """Send briefing as plain text email (legacy)."""
        return self._send(
            subject=briefing.split("\n")[0],
            text_body=briefing,
            html_body=None,
        )

    async def send_articles(self, articles: list[dict], date_str: str) -> bool:
        """Send articles as a formatted HTML email."""
        if not self.recipients:
            logger.warning("No email recipients configured")
            return False

        articles_html = "\n".join(
            ARTICLE_HTML.format(
                title_ko=_escape(a.get("title_ko", a.get("title", ""))),
                summary_ko=_escape(a.get("summary_ko", "")),
                source=_escape(a.get("source", "")),
                url=a.get("url", ""),
            )
            for a in articles
        )

        html = HTML_TEMPLATE.format(
            date=date_str,
            articles_html=articles_html,
            count=len(articles),
        )

        subject = f"🦴 고생물학 뉴스 브리핑 ({date_str}) - {len(articles)}건"

        # Plain text fallback
        text_lines = [f"고생물학 뉴스 브리핑 ({date_str})", ""]
        for a in articles:
            text_lines.append(f"■ {a.get('title_ko', a.get('title', ''))}")
            text_lines.append(a.get("summary_ko", ""))
            text_lines.append(f"  원문: {a.get('url', '')}")
            text_lines.append("")
        text_lines.append(f"총 {len(articles)}건")

        return self._send(subject, "\n".join(text_lines), html)

    def _send(self, subject: str, text_body: str, html_body: str | None) -> bool:
        if not self.recipients:
            logger.warning("No email recipients configured")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.recipients)

        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipients, msg.as_string())
            logger.info("Email sent to %s", ", ".join(self.recipients))
            return True
        except Exception:
            logger.exception("Failed to send email")
            return False


def _escape(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
