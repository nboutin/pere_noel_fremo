import argparse
import logging
import logging.handlers
from pathlib import Path

import yaml

from . import helper

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RES_DIR = PROJECT_ROOT / "res"
DEFAULT_YEAR = 2025


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Envoi de l'annonce officielle du Père Noël secret de la Frémo")
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR, help="Année de l'édition (ex. 2025)")
    parser.add_argument(
        "--skip",
        type=lambda s: [item.strip() for item in s.split(",") if item.strip()] if s else [],
        default=[],
        help="Liste d'identifiants de Lutins absents séparés par des virgules (ex. 'lutin_1,lutin_2')",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Load data from external file and send email to each person"""
    parser = build_parser()
    args = parser.parse_args(argv)

    _configure_logger("email_annonce.log")
    logger.info(f"##### Le Pere Noel de la Fremo ({args.year}) #####")

    secure_data_filepath = RES_DIR / "secure_data.yml"
    email_text_filepath = RES_DIR / f"{args.year}" / "annonce.txt"
    email_subject = f"[Annonce Pole Nord Emploi] Recherche Lutin lugeur et lugeuse pour Noël {args.year}"

    with open(secure_data_filepath, encoding="utf-8") as stream:
        secure_data = yaml.safe_load(stream)

    with open(email_text_filepath, encoding="utf-8") as file:
        body = file.read()

    for lutin_id, id_param in secure_data["personnes"].items():
        if lutin_id in args.skip:
            logger.info(f"Skipping absent Lutin: {lutin_id}")
            continue
        helper.gmail_send_email(secure_data["sender_email"], email_subject, body, id_param["email"])

    logger.info("Finish")


def _configure_logger(filename: str) -> None:
    helper.configure_logger(filename)


if __name__ == "__main__":
    main()
