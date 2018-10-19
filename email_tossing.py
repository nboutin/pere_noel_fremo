#!/usr/bin/env python
# coding: utf-8

import yaml

import smtplib
from email.MIMEMultipart import MIMEMultipart
from email.MIMEText import MIMEText

from random import randint

def main():
    print ("##### Le Pere Noel de la Fremo #####")
    
    with open("res/data.yml", 'r') as stream:
        data = yaml.safe_load(stream)
        
#     for e in data:
#         print(e)
        
    with open("res/secure_data.yml",'r') as stream:
        secure_data = yaml.safe_load(stream)
        
#     print(secure_data)

    tossing(data)


def tossing(data):
    
    TRY_MAX = 10000
    cpt = 0
    users_done = []
    users_togift = []
    
    while(len(users_done) < len(data) and cpt < TRY_MAX):
        cpt += 1
        r1 = randint(0, len(data))-1
        r2 = randint(0, len(data))-1
        
        user_current = data[r1]['id']
        user_togift = data[r2]['id']
        
        if(r1 == r2): # same peson
            continue
        
        if(user_current in users_done): # already done
            continue
        
        if(user_togift in users_togift): # already choosen
            continue
        
        if(data[r1]['couple'] == user_togift): # in couple
            continue
        
        if(user_togift in data[r1]['history']): # choose last years
            continue
        
        # All Good
        users_done.append(user_current)
        users_togift.append(user_togift)
        data[r1]['history'].append(user_togift)
        
        print(user_current, "->", data[r1]['history'][-1])
        
    if(cpt >= TRY_MAX):
        print ("Error: tossing")
        return False
    else:
        return True
    

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