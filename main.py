#!/usr/bin/env python

import yaml

def main():
    print ("##### Le Pere Noel de la Fremo #####")
    
    with open("data.yml", 'r') as stream:
        data = yaml.safe_load(stream)
        
    print (data)
    

if __name__ == "__main__":
    main()