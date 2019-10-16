#!/usr/bin/env python
# coding: utf-8

import yaml
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def main():
    print ("##### Le Pere Noel de la Fremo #####")
    
    with open("res/secure_data.yml",'r') as stream:
        secure_data = yaml.safe_load(stream)

    # debug        
#     secure_data['emails'] = list()
#     secure_data['emails'].append({'id':'nboutin', 'email':'boutwork@gmail.com'})
    # debug

    email_objet = "[Annonce Emploi] Pole Nord Compagnie recherche Lutins polyvalents"
    with open('res/annonce_2019.txt', 'r') as file:
        body = file.read()
        
    for emails in secure_data['emails']:
        send_email(secure_data, email_objet, body, emails['email'])
    
    print("Finish")


def send_email(secure_data, subject, body, toaddr):
    # http://naelshiab.com/tutoriel-comment-envoyer-un-courriel-avec-python/
    print ("sending email... to " + toaddr)
    
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


if __name__ == "__main__":
    main()