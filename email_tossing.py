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
        
    with open("res/secure_data.yml",'r') as stream:
        secure_data = yaml.safe_load(stream)
        
    if(not tossing(data)):
        exit()
        
    send_all_email(data, secure_data)
        
        
def send_all_email(data, secure_data):
    
    subject='Le Père Noël de la Frémo a besoin de ton aide'
    
    for person in data:
        secure_email = [x for x in secure_data['emails'] if x['id'] == person['id']]
        toaddr = secure_email[0]['email']
        
        to_gift_id = person['history'][-1]
        person_togift = [x for x in data if x['id'] == to_gift_id]
        to_fullname = person_togift[0]['fullname']
        
        body=u""""<h3>HOHOHO,</h3>
            <p>
            Bonjour petit lutin %s,<br>
            <br>
            Cette année pour conserver la magie de Noël, je souhaiterai que tu fasses un cadeau à %s.
            Malheureusement, je n'ai même pas d'idée à te fournir pour t'aider mais en faisant appel à 
            ton imagination, tu trouveras le cadeau idéal !<br>
            <br>
            Cette année j'ai recu un plein de jolie dessin. D'ailleurs, j'en attends toujours un dernier...
            Une exposition va être mise en place afin de voter pour le plus beau, 
            le gagnant recevra en premier son cadeau.<br>
            </p>
            <h3>Le Père Noël de la Frémo</h3>""" % (person['fullname'], to_fullname)

#         print(person['id'] , "->", to_fullname, '(', to_gift_id,')')
        send_email(secure_data, subject, body.encode('utf8'), toaddr)


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
        
        if(r1 == r2): # same person
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
        print ("error")
        return False
    else:
        print ("done")
        return True
    

def is_loop(data):
    
    in_loop= []
    

def send_email(secure_data, subject, body, toaddr):
    # http://naelshiab.com/tutoriel-comment-envoyer-un-courriel-avec-python/
    print(toaddr, "-> sending email...",end='')
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