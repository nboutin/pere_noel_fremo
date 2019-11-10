#!/usr/bin/env python
# encoding=utf8

import sys
import yaml
from random import randint
import helper

def main():
    print ("##### Le Pere Noel de la Fremo #####")
    
    with open("res/data_2019.yml", 'r') as stream:
        data = yaml.safe_load(stream)
        
    with open("res/secure_data.yml",'r') as stream:
        secure_data = yaml.safe_load(stream)
        
    if(not tossing(data)):
        sys.exit()
        
    send_all_email(data, secure_data)
        
        
def send_all_email(data, secure_data):
    
    subject='Le Père Noël de la Frémo a besoin de ton aide'
    
    for person in data:
        secure_email = [x for x in secure_data['emails'] if x['id'] == person['id']]
        toaddr = secure_email[0]['email']
#         toaddr = secure_data['receiver_test']
        
        to_gift_id = person['history'][-1]
        person_togift = [x for x in data if x['id'] == to_gift_id]
        to_fullname = person_togift[0]['fullname']
        
        with open('res/tossing_2019.txt', 'r') as file:
            body = file.read().format(person['fullname'], to_fullname)
        
#         print(person['id'] , "->", to_fullname, '(', to_gift_id,')')
        helper.send_email(secure_data, subject, body, toaddr)


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
    

if __name__ == "__main__":
    main()