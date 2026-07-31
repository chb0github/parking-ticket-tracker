"""Send the report via Gmail SMTP, Python-native (no curl).

Credentials come from ~/.netrc (machine smtp.gmail.com) using the stdlib
`netrc` module — the same app password the host's existing scripts use. The
login there is a Gmail app password, not the account password.
"""

from __future__ import annotations

import netrc
import smtplib
import ssl
from email.message import EmailMessage

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


class MailError(RuntimeError):
    pass


def _credentials(host=SMTP_HOST):
    """Return (login, app_password) from ~/.netrc for the SMTP host."""
    try:
        auth = netrc.netrc().authenticators(host)
    except (FileNotFoundError, netrc.NetrcParseError) as e:
        raise MailError(f"cannot read ~/.netrc: {e}") from e
    if not auth:
        raise MailError(f"no ~/.netrc entry for machine {host}")
    login, _account, password = auth
    if not login or not password:
        raise MailError(f"~/.netrc entry for {host} is missing login or password")
    return login, password


def send(recipients, subject, html_body, text_body, sender=None, inline_images=None):
    """Send one multipart (text + HTML) email to all recipients.

    recipients: list of addresses. sender defaults to the .netrc login.
    inline_images: optional list of (cid, filepath) tuples embedded in the HTML
        via <img src="cid:..."> as multipart/related parts.
    """
    if isinstance(recipients, str):
        recipients = [recipients]
    recipients = [r for r in recipients if r]
    if not recipients:
        raise MailError("no recipients given")

    login, password = _credentials()
    from_addr = sender or login

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(text_body or "See the HTML version of this report.")
    msg.add_alternative(html_body, subtype="html")

    # Attach inline images to the HTML alternative (multipart/related).
    if inline_images:
        # The HTML alternative is the last part added; add_related nests it.
        html_part = list(msg.iter_parts())[-1]
        for cid, path in inline_images:
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                # Non-fatal: the HTML has a graceful fallback if the image is missing.
                continue
            html_part.add_related(data, maintype="image", subtype="png", cid=f"<{cid}>")

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=30) as smtp:
            smtp.login(login, password)
            smtp.send_message(msg, from_addr=from_addr, to_addrs=recipients)
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f"SMTP send failed: {e}") from e
