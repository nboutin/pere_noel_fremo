#!/usr/bin/env python

import yaml
import smtplib
from email.MIMEMultipart import MIMEMultipart
from email.MIMEText import MIMEText

def main():
    print ("##### Le Pere Noel de la Fremo #####")
    
    with open("data.yml", 'r') as stream:
        data = yaml.safe_load(stream)
        
    for e in data:
        print(e)
        
    with open("secure_data.yml",'r') as stream:
        secure_data = yaml.safe_load(stream)
        
    print(secure_data)

    send_email(secure_data)

def send_email(secure_data):
    # http://naelshiab.com/tutoriel-comment-envoyer-un-courriel-avec-python/
    print ("sending email...")
    fromaddr = secure_data['sender_email']
    toaddr = secure_data['receiver_test']
    msg = MIMEMultipart()
    msg['From'] = fromaddr
    msg['To'] = toaddr
    msg['Subject'] = "SUBJECT OF THE MAIL"
     
    body = "YOUR MESSAGE HERE"
    msg.attach(MIMEText(body, 'plain'))
     
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(fromaddr, secure_data['sender_pwd'])
    text = msg.as_string()
    server.sendmail(fromaddr, toaddr, text)
    server.quit()

    print("done")


if __name__ == "__main__":
    main()