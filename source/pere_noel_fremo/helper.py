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

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def resolve_res_dir() -> Path:
    env_dir = os.environ.get("FREMO_RES_DIR")
    if env_dir:
        return Path(env_dir)
    app_res = Path("/app/res")
    if app_res.exists():
        return app_res
    return PROJECT_ROOT / "res"


RES_DIR = resolve_res_dir()
LOGS_DIR = Path(os.environ.get("FREMO_LOGS_DIR", "/app/logs" if Path("/app/logs").exists() else PROJECT_ROOT / "logs"))

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
TOKEN_PATH = RES_DIR / "token.json"  # nosec B105
CREDENTIALS_PATH = RES_DIR / "code_secret_client.apps.googleusercontent.com.json"
# IMG_BACKGROUND_URL = 'https://i.ibb.co/cD0Ddqb/2023-pere-noel-fait-du-ski-800.png'
IMG_FILEPATH = RES_DIR / "img" / "snow_rider_3d_B.png"


def configure_logger(filename: str) -> None:
    """Configure root logger with console INFO and rotating file DEBUG in LOGS_DIR."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_filepath = LOGS_DIR / filename

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


def load_credentials() -> Credentials:
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
    return cast(Credentials, creds)


def create_message(
    sender_email: str, subject: str, body: str, toaddr: str, img_path: str | None = None
) -> dict[str, str]:
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = toaddr

    msgAlternative = MIMEMultipart("alternative")
    msg.attach(msgAlternative)

    msgText = MIMEText("This is the alternative plain text message.")
    msgAlternative.attach(msgText)

    # We reference the image in the IMG SRC attribute by the ID we give it below
    msgText = MIMEText('<img src="cid:image1"><br>' + body, "html")
    msgAlternative.attach(msgText)

    if img_path:
        # This example assumes the image is in the current directory
        with open(img_path, "rb") as fp:
            msgImage = MIMEImage(fp.read())

        # Define the image's ID as referenced above
        msgImage.add_header("Content-ID", "<image1>")
        msg.attach(msgImage)

    # encoded message
    encoded_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    return {"raw": encoded_message}


def gmail_send_email(sender_email: str, subject: str, body: str, toaddr: str) -> Any:
    try:
        creds = load_credentials()
        service = build("gmail", "v1", credentials=creds)
        message = create_message(sender_email, subject, body, toaddr, None)
        # message = create_message(sender_email, subject, body, toaddr, IMG_FILEPATH)
        send_message = service.users().messages().send(userId="me", body=message).execute()
        logger.info(f"Sent to {toaddr}")
    except Exception as error:
        logger.error(f"An error occurred: {error}")
        send_message = None
    return send_message
