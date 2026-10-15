#!/usr/bin/env python
# pylint: disable=logging-fstring-interpolation

import base64
import logging
import logging.handlers
import os
import os.path
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import resolve_logs_dir, resolve_res_dir

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


def get_token_path() -> Path:
    return resolve_res_dir() / "token.json"


def get_credentials_path() -> Path:
    return resolve_res_dir() / "code_secret_client.apps.googleusercontent.com.json"


def get_img_filepath() -> Path:
    return resolve_res_dir() / "img" / "snow_rider_3d_B.png"


def configure_logger(filename: str) -> None:
    """Configure root logger with console INFO and rotating file DEBUG in LOGS_DIR."""
    logs_dir = resolve_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_filepath = logs_dir / filename

    root_logger = logging.getLogger("")
    root_logger.setLevel(logging.DEBUG)

    # Check if a FileHandler targeting this file already exists
    has_file_handler = any(
        isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == str(log_filepath.resolve())
        for h in root_logger.handlers
    )

    if not has_file_handler:
        file_handler = logging.handlers.RotatingFileHandler(
            str(log_filepath), maxBytes=1024 * 1024, backupCount=1, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            fmt="[%(asctime)s][%(name)s][%(levelname)-5s]%(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    has_console_handler = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root_logger.handlers
    )
    if not has_console_handler:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter("%(message)s")
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)


class EmailSendError(Exception):
    """Exception levée en cas d'échec lors de l'envoi d'un courriel via Gmail."""


def load_credentials(interactive: bool = False) -> Credentials:
    """Charge les identifiants Gmail.

    En mode non interactif (défaut), un jeton absent ou non rafraîchissable lève ``EmailSendError``
    au lieu d'ouvrir un navigateur (``run_local_server`` est bloquant et sans délai d'expiration).
    """
    creds = None
    token_path = get_token_path()
    credentials_path = get_credentials_path()
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refreshed = bool(creds.valid)
            except Exception as e:
                logger.warning(f"Impossible de rafraîchir le jeton expiré ({e}), ré-authentification requise.")
        if not refreshed:
            if not interactive:
                raise EmailSendError("Jeton Gmail invalide : ré-authentifier en local")
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)
        if creds:
            with open(token_path, "w", encoding="utf-8") as token:
                token.write(creds.to_json())
    return cast(Credentials, creds)


def build_gmail_service(interactive: bool = False) -> Any:
    """Construit le service Gmail (une seule fois par campagne)."""
    creds = load_credentials(interactive=interactive)
    return build("gmail", "v1", credentials=creds)


def create_message(
    sender_email: str,
    subject: str,
    body: str,
    toaddr: str,
    img_path: str | None = None,
    text_body: str | None = None,
) -> dict[str, str]:
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = toaddr

    msgAlternative = MIMEMultipart("alternative")
    msg.attach(msgAlternative)

    plain_content = text_body if text_body is not None else "This is the alternative plain text message."
    msgText = MIMEText(plain_content, "plain", "utf-8")
    msgAlternative.attach(msgText)

    if img_path:
        # We reference the image in the IMG SRC attribute by the ID we give it below
        msgHtml = MIMEText('<img src="cid:image1"><br>' + body, "html", "utf-8")
        msgAlternative.attach(msgHtml)

        # This example assumes the image is in the current directory
        with open(img_path, "rb") as fp:
            msgImage = MIMEImage(fp.read())

        # Define the image's ID as referenced above
        msgImage.add_header("Content-ID", "<image1>")
        msg.attach(msgImage)
    else:
        msgHtml = MIMEText(body, "html", "utf-8")
        msgAlternative.attach(msgHtml)

    # encoded message
    encoded_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    return {"raw": encoded_message}


def gmail_send_email(
    service: Any,
    sender_email: str,
    subject: str,
    body: str,
    toaddr: str,
    text_body: str | None = None,
) -> Any:
    try:
        message = create_message(sender_email, subject, body, toaddr, None, text_body=text_body)
        # message = create_message(sender_email, subject, body, toaddr, IMG_FILEPATH)
        send_message = service.users().messages().send(userId="me", body=message).execute()
        logger.info(f"Sent to {toaddr}")
        return send_message
    except Exception as error:
        logger.error(f"Failed to send email to {toaddr}: {error}")
        raise EmailSendError(f"Failed to send email to {toaddr}: {error}") from error


FRENCH_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
FRENCH_MONTHS = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


def format_date_repas(
    date_str: str | None,
    now: Any = None,
) -> dict[str, Any] | None:
    """Formate la date ISO du Repas de Noël en français et calcule le compte à rebours J-xx.

    Zéro dépendance externe.
    """
    if not date_str or not str(date_str).strip():
        return None

    clean_str = str(date_str).strip()[:10]
    try:
        from datetime import date, datetime, timezone

        d = date.fromisoformat(clean_str)
    except Exception:
        return None

    if now is None:
        today = datetime.now(timezone.utc).date()
    elif isinstance(now, datetime):
        today = now.date()
    else:
        today = now

    delta_days = (d - today).days

    jour_nom = FRENCH_DAYS[d.weekday()]
    mois_nom = FRENCH_MONTHS[d.month - 1]
    formatted = f"{jour_nom} {d.day} {mois_nom} {d.year}"

    if delta_days > 0:
        countdown = f"J-{delta_days}"
    elif delta_days == 0:
        countdown = "Aujourd'hui ! 🎅"
    else:
        countdown = "Passé"

    return {
        "raw": date_str,
        "formatted": formatted,
        "delta_days": delta_days,
        "countdown": countdown,
    }


def __getattr__(name: str) -> Any:
    if name == "RES_DIR":
        return resolve_res_dir()
    if name == "LOGS_DIR":
        return resolve_logs_dir()
    if name == "TOKEN_PATH":
        return get_token_path()
    if name == "CREDENTIALS_PATH":
        return get_credentials_path()
    if name == "IMG_FILEPATH":
        return get_img_filepath()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
