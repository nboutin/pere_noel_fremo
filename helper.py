#!/usr/bin/env python
# coding: utf-8

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(secure_data, subject, body, toaddr):
    # http://naelshiab.com/tutoriel-comment-envoyer-un-courriel-avec-python/
    print ("sending email... to " + toaddr + " ", end='')
    
    fromaddr = secure_data['sender_email']
    msg = MIMEMultipart()
    msg['From'] = fromaddr
    msg['To'] = toaddr
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))
     
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(fromaddr, secure_data['sender_pwd'])
    text = msg.as_string()
    server.sendmail(fromaddr, toaddr, text)
    server.quit()

    print("done")
