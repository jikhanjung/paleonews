import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .base import BaseDispatcher

logger = logging.getLogger(__name__)


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
        """Send briefing as email newsletter."""
        if not self.recipients:
            logger.warning("No email recipients configured")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = briefing.split("\n")[0]  # First line as subject
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.recipients)

        # Plain text version
        msg.attach(MIMEText(briefing, "plain", "utf-8"))

        # HTML version
        html = "<pre style='font-family: sans-serif;'>" + briefing.replace("\n", "<br>") + "</pre>"
        msg.attach(MIMEText(html, "html", "utf-8"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipients, msg.as_string())
            logger.info("Email sent to %d recipients", len(self.recipients))
            return True
        except Exception:
            logger.exception("Failed to send email")
            return False
