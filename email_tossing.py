#!/usr/bin/env python
# encoding=utf8

import yaml
from random import randint
import helper
import logging.handlers

logger = logging.getLogger(__name__)

__SECURE_DATA = "res/secure_data.yml"
__DATA = "res/data_2021.yml"
__BODY = "res/tossing_2021.txt"


def main():
    _configure_logger('email_tossing.log')
    logger.info("##### Le Pere Noel de la Fremo #####")

    with open(__DATA, 'r') as stream:
        data = yaml.safe_load(stream)

    retry_count = 10
    while(not tossing(data) and retry_count > 0):
        logger.warning("Tossing ({}) did not found solution, restarting..".format(retry_count))
        retry_count -= 1

    with open(__SECURE_DATA, 'r') as stream:
        secure_data = yaml.safe_load(stream)
        
    send_all_email(data, secure_data)

    # export new data
    with open('res/data_export.yml', 'w') as file:
        yaml.dump(data, file, allow_unicode=True)
        
    logger.info("Tossing is done")


def send_all_email(data, secure_data):

    subject = 'Le Père Noël de la Frémo: Tirage au sort'

    for id_, id_param in data.items():
        toaddr = secure_data['personnes'][id_]['email']
        # DEBUG
        # toaddr = secure_data['receiver_test']
        # DEBUG

        to_gift_id = id_param['history'][-1]
        to_fullname = data[to_gift_id]['fullname']

        with open(__BODY, 'r') as file:
            body = file.read().format(id_param['fullname'], to_fullname)

        logger.debug("{} -> {} ({})".format(id_, to_fullname, to_gift_id))
        helper.send_email(secure_data['sender_email'], secure_data['sender_pwd'], subject, body, toaddr)


def tossing(data):

    logger.info("Tossing...")

    TRY_MAX = 100000
    retry_count = 0
    users_done = []
    users_gifted = []

    while(len(users_done) < len(data) and retry_count < TRY_MAX):
        retry_count += 1
        r1 = randint(0, len(data)) - 1
        r2 = randint(0, len(data)) - 1

        user_current = list(data)[r1]
        user_togift = list(data)[r2]

        if(r1 == r2):  # same person
            continue

        if(user_current in users_done):  # already done
            continue

        if(user_togift in users_gifted):  # already chosen
            continue

        if(user_togift in data[user_current]['exclude']):  # excluded
            continue

        if(user_togift in data[user_current]['history']):  # chosen last years
            continue

        # All Good
        users_done.append(user_current)
        users_gifted.append(user_togift)
        data[user_current]['history'].append(user_togift)

        logger.debug("{} -> {}".format(user_current, data[user_current]['history'][-1]))

    if(retry_count >= TRY_MAX):
        logger.error("Error: too much tossing")
        return False
    else:
        logger.info("Success ({})".format(retry_count))
        return True


def is_loop(data):

    in_loop = []


def _configure_logger(filename):
    """
    write to console, simple message with log level info
    write to file, formatted message with log level debug
    """
    logger = logging.getLogger('')
    logger.setLevel(logging.DEBUG)

    # Console
    consoleHandler = logging.StreamHandler()
    consoleHandler.setLevel(logging.INFO)
    consoleFormatter = logging.Formatter('%(message)s')
    consoleHandler.setFormatter(consoleFormatter)
    logger.addHandler(consoleHandler)

    # File
    fileHandler = logging.handlers.RotatingFileHandler(filename, maxBytes=1024 * 1024, backupCount=1)
    fileHandler.setLevel(logging.DEBUG)
    fileFormatter = logging.Formatter(
        fmt='[%(asctime)s][%(name)s][%(levelname)-5s]%(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')
    fileHandler.setFormatter(fileFormatter)
    logger.addHandler(fileHandler)


if __name__ == "__main__":
    main()
