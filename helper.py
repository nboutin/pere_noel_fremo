#!/usr/bin/env python
# coding: utf-8

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


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
