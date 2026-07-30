"""
Email message construction with placeholder substitution and randomized headers.
"""
import re
import uuid
import random
import string
import os
import time
import logging
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Any, Dict, List, Optional

try:
    from faker import Faker
    _fake = Faker()
    FAKER_AVAILABLE = True
except ImportError:
    _fake = None
    FAKER_AVAILABLE = False

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Microsoft Outlook/16.0.14831.20648",
    "Microsoft Outlook/15.0.4815.1002",
    "Thunderbird/102.12.0",
    "Thunderbird/91.13.0",
    "Apple Mail/16.0 (3731.500.231.1.3)",
    "Opera Mail/3.0",
    "The Bat! (v10.5.1.2)",
    "Windows Live Mail 2012",
    "Postfix MTA 3.7",
]

X_MAILERS = [
    "Microsoft Outlook 16.0",
    "Microsoft Outlook 15.0",
    "Thunderbird 102.12",
    "Apple Mail (3731.500.231)",
    "Windows Live Mail 2012",
    "Postbox 7.0.54",
    "eM Client 9.2",
]


# ---------------------------------------------------------------------------
# Placeholder engine
# ---------------------------------------------------------------------------

def _get_fake_names():
    if FAKER_AVAILABLE:
        return _fake.first_name(), _fake.last_name()
    first = random.choice(["James", "John", "Robert", "Michael", "William",
                           "Mary", "Patricia", "Jennifer", "Linda", "Barbara"])
    last = random.choice(["Smith", "Johnson", "Williams", "Brown", "Jones",
                          "Garcia", "Miller", "Davis", "Wilson", "Moore"])
    return first, last


def replace_placeholders(
    text: str,
    recipient_email: str,
    links_list: Optional[List[str]] = None,
) -> str:
    """
    Replace all %PLACEHOLDER% tags in text.

    Supported tags:
      %EMAIL%            full recipient email
      %DOMAIN%           domain name part (capitalized)
      %FIRSTNAME%        random first name (or domain-derived)
      %LAST%             random last name
      %FULLNAME%         first + last
      %DOMAIN_FIRSTNAME% domain_FirstName
      %DATE%             current date YYYY-MM-DD
      %TIME%             current time HH:MM:SS
      %RANDOMENUM%       8 random digits
      %RANDOMSTR%        8 random alphanumeric chars
      %LINK%             random link from links_list
    """
    if not text:
        return text

    first, last = _get_fake_names()
    try:
        domain_part = recipient_email.split("@")[1].split(".")[0].capitalize()
    except IndexError:
        domain_part = "User"

    link = random.choice(links_list) if links_list else ""

    mapping = {
        "%EMAIL%": recipient_email,
        "%DOMAIN%": domain_part,
        "%FIRSTNAME%": first,
        "%LAST%": last,
        "%FULLNAME%": f"{first} {last}",
        "%DOMAIN_FIRSTNAME%": f"{domain_part}_{first}",
        "%DATE%": datetime.now().strftime("%Y-%m-%d"),
        "%TIME%": datetime.now().strftime("%H:%M:%S"),
        "%RANDOMENUM%": "".join(random.choices(string.digits, k=8)),
        "%RANDOMSTR%": "".join(random.choices(string.ascii_letters + string.digits, k=8)),
        "%LINK%": link,
    }

    for tag, val in mapping.items():
        text = text.replace(tag, val)
    return text


# ---------------------------------------------------------------------------
# Message-ID / Date helpers
# ---------------------------------------------------------------------------

def generate_message_id(domain: str) -> str:
    rand = uuid.uuid4().hex
    ts = hex(int(time.time()))[2:]
    rnd = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"<{ts}.{rnd}.{rand}@{domain}>"


def random_rfc_date() -> str:
    """Date ± random offset to avoid pattern detection."""
    offset = random.randint(-3600, 3600)
    dt = datetime.now() + timedelta(seconds=offset)
    # RFC 2822 format
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


# ---------------------------------------------------------------------------
# Body loader
# ---------------------------------------------------------------------------

def load_body(config: Dict[str, Any], recipient: str, links_list: List[str]) -> str:
    """
    Load message body from config.
    Priority: message_body_file > message_body (inline string).
    """
    body_file = config.get("message_body_file", "")
    if body_file and os.path.exists(body_file):
        try:
            with open(body_file, "r", encoding="utf-8") as f:
                raw = f.read()
            return replace_placeholders(raw, recipient, links_list)
        except Exception as e:
            logger.error(f"Failed to read body file {body_file}: {e}")

    raw = config.get("message_body", "")
    return replace_placeholders(raw, recipient, links_list)


# ---------------------------------------------------------------------------
# PDF generation (optional)
# ---------------------------------------------------------------------------

def generate_pdf_bytes(
    html_content: str,
    recipient: str,
    links_list: List[str],
    wkhtmltopdf_path: str = "",
) -> Optional[bytes]:
    try:
        import pdfkit
        import io

        content = replace_placeholders(html_content, recipient, links_list)
        options = {
            "page-size": "A4",
            "margin-top": "0.75in",
            "margin-right": "0.75in",
            "margin-bottom": "0.75in",
            "margin-left": "0.75in",
            "encoding": "UTF-8",
            "no-outline": None,
            "quiet": "",
        }

        if wkhtmltopdf_path and os.path.exists(wkhtmltopdf_path):
            cfg = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)
            pdf_bytes = pdfkit.from_string(content, False, options=options, configuration=cfg)
        else:
            pdf_bytes = pdfkit.from_string(content, False, options=options)

        # Inject unique metadata via pypdf
        try:
            from pypdf import PdfReader, PdfWriter
            reader = PdfReader(io.BytesIO(pdf_bytes))
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            writer.add_metadata({
                "/Title": replace_placeholders("Doc %RANDOMENUM%", recipient, links_list),
                "/Author": replace_placeholders("%FULLNAME%", recipient, links_list),
                "/Subject": replace_placeholders("%DOMAIN_FIRSTNAME%", recipient, links_list),
            })
            buf = io.BytesIO()
            writer.write(buf)
            return buf.getvalue()
        except Exception:
            return pdf_bytes

    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_email(
    config: Dict[str, Any],
    recipient: str,
    links_list: List[str],
    from_email: str = "",
    sender_name: str = "",
) -> str:
    """
    Build a fully-formed RFC 2822 email message string ready to pass to
    smtplib's data() or sendmail().
    """
    body_type = config.get("message_body_type", "html")
    body = load_body(config, recipient, links_list)

    _sender_name = replace_placeholders(
        sender_name or config.get("sender_name", ""),
        recipient, links_list,
    )
    _subject = replace_placeholders(config.get("subject", ""), recipient, links_list)

    try:
        domain = from_email.split("@")[1] if "@" in from_email else "mail.local"
    except Exception:
        domain = "mail.local"

    msg = MIMEMultipart("mixed")
    msg["From"] = f"{_sender_name} <{from_email}>" if _sender_name else from_email
    msg["To"] = recipient
    msg["Subject"] = _subject
    msg["Message-ID"] = generate_message_id(domain)
    msg["Date"] = random_rfc_date()
    msg["User-Agent"] = random.choice(USER_AGENTS)
    msg["X-Mailer"] = random.choice(X_MAILERS)
    msg["X-Originating-IP"] = (
        f"{random.randint(1,223)}.{random.randint(0,255)}"
        f".{random.randint(0,255)}.{random.randint(1,254)}"
    )
    msg["X-Priority"] = str(random.randint(1, 3))
    if random.random() > 0.4:
        msg["X-MSMail-Priority"] = random.choice(["High", "Normal", "Low"])
    if random.random() > 0.6:
        msg["Importance"] = random.choice(["high", "normal", "low"])

    # Body
    msg.attach(MIMEText(body, body_type, "utf-8"))

    # PDF attachment
    if config.get("html2pdf", False):
        html_file = replace_placeholders(config.get("html2pdf_file", ""), recipient, links_list)
        if html_file and os.path.exists(html_file):
            try:
                with open(html_file, "r", encoding="utf-8") as f:
                    html_content = f.read()
                pdf_bytes = generate_pdf_bytes(
                    html_content, recipient, links_list,
                    wkhtmltopdf_path=config.get("wkhtmltopdf_path", ""),
                )
                if pdf_bytes:
                    attach_name = replace_placeholders(
                        config.get("html2pdf_attachment_name", "document.pdf"),
                        recipient, links_list,
                    )
                    part = MIMEBase("application", "pdf")
                    part.set_payload(pdf_bytes)
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f'attachment; filename="{attach_name}"')
                    msg.attach(part)
            except Exception as e:
                logger.error(f"Attachment error for {recipient}: {e}")

    # Generic file attachment
    attachment_path = config.get("attachment_path", "")
    if attachment_path and os.path.exists(attachment_path):
        try:
            with open(attachment_path, "rb") as f:
                data = f.read()
            part = MIMEBase("application", "octet-stream")
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{os.path.basename(attachment_path)}"',
            )
            msg.attach(part)
        except Exception as e:
            logger.error(f"File attachment error for {recipient}: {e}")

    return msg.as_string()
