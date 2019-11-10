#!/usr/bin/env python
# coding: utf-8

import yaml
import helper


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
        helper.send_email(secure_data, email_objet, body, emails['email'])
    
    print("Finish")


if __name__ == "__main__":
    main()