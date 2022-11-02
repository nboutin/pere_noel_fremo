#!/usr/bin/env python
# coding: utf-8

import yaml
import helper
import logging.handlers

logger = logging.getLogger(__name__)

__SECURE_DATA_FILEPATH = "res/secure_data.yml"
__EMAIL_TEXT_FILE_PATH = 'res/annonce_2022.txt'
__EMAIL_OBJECT = "[Annonce Emploi] Pôle Nord Compagnie recherche Lutins créatifs"


def main():
    _configure_logger('email_annonce.log')
    logger.info("##### Le Pere Noel de la Fremo #####")

    with open(__SECURE_DATA_FILEPATH, 'r') as stream:
        secure_data = yaml.safe_load(stream)

    with open(__EMAIL_TEXT_FILE_PATH, 'r') as file:
        body = file.read()

    # for debug, change key form personnes to personnes_test
    for id_, id_param in secure_data['personnes'].items():
        helper.gmail_send_email(
            secure_data['sender_email'],
            __EMAIL_OBJECT,
            body,
            id_param['email'])

    logger.info("Finish")


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
