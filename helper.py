#!/usr/bin/env python
# coding: utf-8
# pylint: disable=logging-fstring-interpolation

import logging
import base64
import os.path
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
# from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


SCOPES = ['https://www.googleapis.com/auth/gmail.compose']
TOKEN_PATH = 'res/token.json'
CREDENTIALS_PATH = 'res/credentials.json'
IMG_BACKGROUND_URL = 'https://i.ibb.co/cD0Ddqb/2023-pere-noel-fait-du-ski-800.png'
IMG_FILEPATH = 'res/img/2023_pere_noel_fait_du_ski_800.png'


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


def create_message(sender_email, subject, body, toaddr, img_path):
    msg = MIMEMultipart('related')
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = toaddr

    msgAlternative = MIMEMultipart('alternative')
    msg.attach(msgAlternative)

    msgText = MIMEText('This is the alternative plain text message.')
    msgAlternative.attach(msgText)

    # We reference the image in the IMG SRC attribute by the ID we give it below
    msgText = MIMEText('<img src="cid:image1"><br>'+body, 'html')
    msgAlternative.attach(msgText)

    # This example assumes the image is in the current directory
    fp = open(img_path, 'rb')
    msgImage = MIMEImage(fp.read())
    fp.close()

    # Define the image's ID as referenced above
    msgImage.add_header('Content-ID', '<image1>')
    msg.attach(msgImage)

    # encoded message
    encoded_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    return {'raw': encoded_message}


def gmail_send_email(sender_email, subject, body, toaddr):
    try:
        creds = load_credentials()
        service = build('gmail', 'v1', credentials=creds)
        message = create_message(sender_email, subject, body, toaddr, IMG_FILEPATH)
        send_message = (service.users().messages().send(userId="me", body=message).execute())
        logger.info(f"Sent to {toaddr}")
    except Exception as error:
        logger.error(F'An error occurred: {error}')
        send_message = None
    return send_message
