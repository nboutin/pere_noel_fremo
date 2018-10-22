#!/usr/bin/env python
# encoding=utf8

from __future__ import print_function
import yaml
import smtplib
from email.MIMEMultipart import MIMEMultipart
from email.MIMEText import MIMEText
from random import randint

def main():
    print ("##### Le Pere Noel de la Fremo #####")
    
    with open("res/data_2018.yml", 'r') as stream:
        data = yaml.safe_load(stream)
        
    for e in data:
        print(e)
        
    with open("res/secure_data.yml",'r') as stream:
        secure_data = yaml.safe_load(stream)
        
#     print(secure_data)

    if(not tossing(data)):
        exit()
        
    send_all_email(data, secure_data)
        
        
def send_all_email(data, secure_data):
    
    subject=''
    
    for person in data:
        secure_email = [x for x in secure_data['emails'] if x['id'] == person['id']]
        toaddr=secure_email[0]['email']
        to_id = person['history'][-1]
        print(to_id)
        to_fullname=""
        body=u""""<h3>HOHOHO,</h3>
            <p>
            Bonjour petit lutin %s,<br>
            <br>
            Cette année pour conserver la magie de Noël, je souhaiterai que tu fasses un cadeau à %s.
            Malheureusement, je n'ai même pas d'idée à te fournir pour t'aider mais en faisant appel à 
            ton imagination, tu trouveras le cadeau idéal !<br>
            Cette année le plus beau dessin à été réalisé par XXX, il/elle donnera en premier son cadeau.<br>
            </p>
            <h3>Le Père Noël de la Frémo</h3>""" % (person['fullname'], to_fullname)
#         print(body)
#         send_email(secure_data, subject, body, toaddr)


def tossing(data):
    
    print("Tossing...", end='')
    
    TRY_MAX = 100000
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
        
#         print(user_current, "->", data[r1]['history'][-1])
        
    if(cpt >= TRY_MAX):
        print ("Error: tossing")
        return False
    else:
        print ("done")
        return True
    

def is_loop(data):
    
    in_loop= []
    

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