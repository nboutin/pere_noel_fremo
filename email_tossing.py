#!/usr/bin/env python
# encoding=utf8
# pylint: disable=logging-fstring-interpolation

import logging
import logging.handlers
from random import randint
from pathlib import Path

import yaml

import helper

logger = logging.getLogger(__name__)

__YEAR = 2024
__SECURE_DATA = Path(f"res/secure_data.yml")
__DATA_IN = Path(f"res/{__YEAR}/data_in.yml")
__BODY = Path(f"res/{__YEAR}/tossing.txt")
__DATA_OUT = Path(f"res/{__YEAR}/data_out.yml")

PERSON_TO_SKIP = []


def main():
    _configure_logger('email_tossing.log')
    logger.info("##### Le Pere Noel de la Fremo #####")

    with open(__DATA_IN, 'r', encoding='utf-8') as stream:
        data = yaml.safe_load(stream)

    retry_count = 10
    while (not tossing(data, PERSON_TO_SKIP) and retry_count > 0):
        logger.warning(f"Tossing ({retry_count}) did not found solution, restarting...")
        retry_count -= 1

    with open(__SECURE_DATA, 'r', encoding='utf-8') as stream:
        secure_data = yaml.safe_load(stream)

    send_all_email(data, secure_data, PERSON_TO_SKIP)

    # export new data
    with open(__DATA_OUT, 'w', encoding='utf-8') as file:
        yaml.dump(data, file, allow_unicode=True)

    logger.info("Tossing is done")


def send_all_email(data, secure_data, to_skip):

    subject = f'[{__YEAR}] Le Père Noël de la Frémo: Tirage au sort'

    for id_, id_param in data.items():
        to_addr = secure_data['personnes'][id_]['email']
        # DEBUG
        to_addr = secure_data['receiver_test']
        # DEBUG

        if id_ in to_skip:
            continue

        gift_from_fullname = id_param['fullname']
        to_gift_id = id_param['history'][-1]
        to_gift_fullname = data[to_gift_id]['fullname']

        with open(__BODY, 'r', encoding='utf-8') as file:
            body = file.read().format(gift_from_fullname, to_gift_fullname)

        logger.debug(f"{id_} -> {to_gift_fullname} ({to_gift_id})")
        helper.gmail_send_email(secure_data['sender_email'], subject, body, to_addr)


def tossing(data, to_skip=[]):
    """
    @param to_skip: array of id to skip
    """

    logger.info("Tossing...")

    TRY_MAX = 100000
    retry_count = 0
    users_done = []
    users_gifted = []
    users_history = {}

    while (len(users_done) < (len(data) - len(to_skip))) and (retry_count < TRY_MAX):

        retry_count += 1
        r1 = randint(0, len(data)-1)
        r2 = randint(0, len(data)-1)

        user_current = list(data)[r1]
        user_to_gift = list(data)[r2]

        # Cheat
        if user_current == 'fxduret' or user_to_gift == 'amoget':
            user_current = 'fxduret'
            user_to_gift = 'amoget'

        if r1 == r2:  # same person
            continue

        if (user_current in to_skip) or (user_to_gift in to_skip):  # not present this year
            continue

        if user_current in users_done:  # already done
            continue

        if user_to_gift in users_gifted:  # already chosen
            continue

        if user_to_gift in data[user_current]['exclude']:  # excluded
            continue

        if user_to_gift in data[user_current]['history']:  # chosen last years
            continue

        # All Good
        users_done.append(user_current)
        users_gifted.append(user_to_gift)
        users_history[user_current] = user_to_gift

    if retry_count >= TRY_MAX:
        logger.error("Error: too much tossing")
        return False
    else:
        # Update History
        for user_current, user_to_gift in users_history.items():
            data[user_current]['history'].append(user_to_gift)

            logger.debug(f"{user_current} -> {data[user_current]['history'][-1]}")

        logger.info(F"Success (retry:{retry_count})")
        return True


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
