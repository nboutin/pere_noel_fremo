#!/usr/bin/env python
# coding: utf-8

import yaml
import smtplib
from email.MIMEMultipart import MIMEMultipart
from email.MIMEText import MIMEText

def main():
    print ("##### Le Pere Noel de la Fremo #####")
    
    with open("res/data.yml", 'r') as stream:
        data = yaml.safe_load(stream)
        
    for e in data:
        print(e)
        
    with open("res/secure_data.yml",'r') as stream:
        secure_data = yaml.safe_load(stream)
        
    print(secure_data)

    body= """<h3>HOHOHO,</h3>
    <p>
    Noël approche à grand pas et j'ai besoin de volontaires pour m'aider dans la distribution de tous les cadeaux !<br>
    Comme l'année précédente, j'ai besoin de personnels qualifiés. Pour mettre en avant tes qualités artistiques, envoie-moi
    ton plus beau dessin sur le thème de Noël.<br>
    Réponds-moi au plus vite avec ton oeuvre en pièce jointe pour être inscrit sur la liste du père noël. <br>
    Le plus beau d'entre tous aura la chance d'ouvrir le bal des cadeaux ! <br>
    </p>
    <h3>Le Père Noël de la Frémo</h3>"""
    
    for emails in secure_data['emails']:
        print(emails['email'])
        send_email(secure_data, "Le Père Noël de la Frémo recrute", body, emails['email'])
        
    print("Finish")

def send_email(secure_data, subject, body, toaddr):
    # http://naelshiab.com/tutoriel-comment-envoyer-un-courriel-avec-python/
    print ("sending email...")
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