#!/usr/bin/env python
# coding: utf-8
# pylint: disable=logging-fstring-interpolation

import logging
import base64
import os.path
from email.message import EmailMessage

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
# from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


SCOPES = ['https://www.googleapis.com/auth/gmail.compose']
TOKEN_PATH = 'res/token.json'
CREDENTIALS_PATH = 'res/credentials.json'


def load_credentials():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, 'w', encoding='utf-8') as token:
            token.write(creds.to_json())
    return creds


def create_message(sender_email, subject, body, toaddr):
    message = EmailMessage()
    message.set_content(body)
    message['To'] = toaddr
    message['From'] = sender_email
    message['Subject'] = subject
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': encoded_message}


def gmail_send_email(sender_email, subject, body, toaddr):
    try:
        creds = load_credentials()
        service = build('gmail', 'v1', credentials=creds)
        message = create_message(sender_email, subject, body, toaddr)
        send_message = (service.users().messages().send(userId="me", body=message).execute())
        logger.info(f"Sent to {toaddr}")
    except Exception as error:
        logger.error(F'An error occurred: {error}')
        send_message = None
    return send_message
