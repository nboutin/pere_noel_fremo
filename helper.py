#!/usr/bin/env python
# coding: utf-8

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import base64
from email.message import EmailMessage

import os.path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


def gmail_send_email(sender_email, subject, body, toaddr):
    """Create and send an email message
    Print the returned  message id
    Returns: Message object, including message id
    Load pre-authorized user credentials from the environment.
    """
    SCOPES = ['https://www.googleapis.com/auth/gmail.compose']
    creds = None

    if os.path.exists('res/token.json'):
        creds = Credentials.from_authorized_user_file('res/token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('res/credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('res/token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        logger.info("sending email... to {}".format(toaddr))

        service = build('gmail', 'v1', credentials=creds)
        message = EmailMessage()

        message.set_content(body)

        message['To'] = toaddr
        message['From'] = sender_email
        message['Subject'] = subject

        # encoded message
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        create_message = {
            'raw': encoded_message
        }
        # pylint: disable=E1101
        send_message = (service.users().messages().send(userId="me", body=create_message).execute())
        logger.info("done")

    except HttpError as error:
        logger.error(F'An error occurred: {error}')
        send_message = None
    return send_message


def send_email(sender_email, sender_pwd, subject, body, toaddr):
    # http://naelshiab.com/tutoriel-comment-envoyer-un-courriel-avec-python/
    logger.info("sending email... to {}".format(toaddr))

    fromaddr = sender_email
    msg = MIMEMultipart()
    msg['From'] = fromaddr
    msg['To'] = toaddr
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(fromaddr, sender_pwd)
    text = msg.as_string()
    server.sendmail(fromaddr, toaddr, text)
    server.quit()

    logger.info("done")
