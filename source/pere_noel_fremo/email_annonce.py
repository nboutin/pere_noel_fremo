#!/usr/bin/env python

import logging
import logging.handlers
from pathlib import Path

import yaml

from . import helper

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RES_DIR = PROJECT_ROOT / "res"

__SECURE_DATA_FILEPATH = RES_DIR / "secure_data.yml"
__EMAIL_TEXT_FILEPATH = RES_DIR / "2025" / "annonce.txt"
__EMAIL_OBJECT = "[Annonce Pole Nord Emploi] Recherche Lutin lugeur et lugeuse pour Noël 2025"

# TODO: manage skip list
PERSON_TO_SKIP: list[str] = ["sbentabet"]


def main() -> None:
    """Load data from external file and send email to each person"""
    _configure_logger("email_annonce.log")
    logger.info("##### Le Pere Noel de la Fremo #####")

    with open(__SECURE_DATA_FILEPATH, encoding="utf-8") as stream:
        secure_data = yaml.safe_load(stream)

    with open(__EMAIL_TEXT_FILEPATH, encoding="utf-8") as file:
        body = file.read()

    # for debug, change key from personnes to personnes_test
    for _, id_param in secure_data["personnes"].items():
        helper.gmail_send_email(secure_data["sender_email"], __EMAIL_OBJECT, body, id_param["email"])

    logger.info("Finish")


def _configure_logger(filename: str) -> None:
    helper.configure_logger(filename)


if __name__ == "__main__":
    main()
