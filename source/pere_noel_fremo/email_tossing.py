#!/usr/bin/env python
# pylint: disable=logging-fstring-interpolation

import argparse
import logging
import logging.handlers
from pathlib import Path
from random import randint
from typing import Any

import yaml

from . import helper

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RES_DIR = PROJECT_ROOT / "res"

DEFAULT_YEAR = 2025
__CHEATERS: list[dict[str, str]] = [
    # {"giver": "scarre", "gifted": "bamy"},
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tirage au sort du Père Noël secret de la Frémo")
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR, help="Année de l'édition (ex. 2025)")
    parser.add_argument(
        "--skip",
        type=lambda s: [item.strip() for item in s.split(",") if item.strip()] if s else [],
        default=[],
        help="Liste d'identifiants de Lutins absents séparés par des virgules (ex. 'lutin_1,lutin_2')",
    )
    return parser


def validate_lutins_data(data: Any) -> None:
    """Valide la structure et la présence des champs obligatoires pour chaque Lutin."""
    if not isinstance(data, dict) or not data:
        raise ValueError("Les données des Lutins doivent être un dictionnaire non vide.")

    required_fields = {"fullname", "exclude", "history"}
    for lutin_id, params in data.items():
        if not isinstance(params, dict):
            raise ValueError(f"Les paramètres du Lutin '{lutin_id}' doivent être un dictionnaire.")

        missing = required_fields - set(params.keys())
        if missing:
            raise ValueError(f"Le Lutin '{lutin_id}' manque les champs obligatoires : {sorted(list(missing))}.")

        if not isinstance(params["exclude"], list) or not isinstance(params["history"], list):
            raise ValueError(f"Les champs 'exclude' et 'history' du Lutin '{lutin_id}' doivent être des listes.")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    _configure_logger("email_tossing.log")
    logger.info(f"##### Le Pere Noel de la Fremo ({args.year}) #####")

    secure_data_path = RES_DIR / "secure_data.yml"
    data_in_path = RES_DIR / f"{args.year}" / "data_in.yml"
    data_out_path = RES_DIR / f"{args.year}" / "data_out.yml"
    body_path = RES_DIR / f"{args.year}" / "tossing.txt"

    with open(data_in_path, encoding="utf-8") as stream:
        data = yaml.safe_load(stream)

    validate_lutins_data(data)

    retry_count = 10
    while not tossing(data, args.skip) and retry_count > 0:
        logger.warning(f"Tossing ({retry_count}) did not found solution, restarting...")
        retry_count -= 1

    with open(secure_data_path, encoding="utf-8") as stream:
        secure_data = yaml.safe_load(stream)

    send_all_email(data, secure_data, args.skip, args.year, body_path)

    # export new data
    with open(data_out_path, "w", encoding="utf-8") as file:
        yaml.dump(data, file, allow_unicode=True)

    logger.info("Tossing is done")


def send_all_email(
    data: dict[str, Any],
    secure_data: dict[str, Any],
    to_skip: list[str],
    year: int = DEFAULT_YEAR,
    body_path: Path | None = None,
) -> None:
    subject = f"[{year}] Le Père Noël de la Frémo: Tirage au sort"
    template_path = body_path if body_path is not None else (RES_DIR / f"{year}" / "tossing.txt")

    for id_, id_param in data.items():
        if id_ in to_skip:
            continue

        to_addr = secure_data["personnes"][id_]["email"]
        gift_from_fullname = id_param["fullname"]
        to_gift_id = id_param["history"][-1]
        to_gift_fullname = data[to_gift_id]["fullname"]

        with open(template_path, encoding="utf-8") as file:
            body = file.read().format(gift_from_fullname, to_gift_fullname)

        logger.debug(f"{id_} -> {to_gift_fullname} ({to_gift_id})")
        helper.gmail_send_email(secure_data["sender_email"], subject, body, to_addr)


def tossing(
    data: dict[str, Any],
    to_skip: list[str] | None = None,
    cheaters: list[dict[str, str]] | None = None,
) -> bool:
    """
    @param to_skip: list of id to skip
    @param cheaters: list of forced pairs (defaults to __CHEATERS)
    """
    if to_skip is None:
        to_skip = []
    cheaters_list = cheaters if cheaters is not None else __CHEATERS

    logger.info("Tossing...")

    MAX_ATTEMPTS = 500
    MAX_STEPS_PER_ATTEMPT = 2000
    target_count = len(data) - len(to_skip)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        users_done: list[str] = []
        users_gifted: list[str] = []
        users_history: dict[str, str] = {}
        steps = 0

        while len(users_done) < target_count and steps < MAX_STEPS_PER_ATTEMPT:
            steps += 1
            r1 = randint(0, len(data) - 1)
            r2 = randint(0, len(data) - 1)

            user_giver = list(data)[r1]
            user_gifted = list(data)[r2]

            # Cheat
            for cheater in cheaters_list:
                if user_giver == cheater["giver"] or user_gifted == cheater["gifted"]:
                    user_giver = cheater["giver"]
                    user_gifted = cheater["gifted"]
                    break

            if r1 == r2:  # same person
                continue

            if (user_giver in to_skip) or (user_gifted in to_skip):  # not present this year
                continue

            if user_giver in users_done:  # already done
                continue

            if user_gifted in users_gifted:  # already chosen
                continue

            if user_gifted not in data:  # cheater target not in participants data
                continue

            if user_gifted in data[user_giver]["exclude"]:  # excluded
                continue

            if user_gifted in data[user_giver]["history"]:  # chosen last years
                continue

            # All Good
            users_done.append(user_giver)
            users_gifted.append(user_gifted)
            users_history[user_giver] = user_gifted

        if len(users_done) == target_count:
            # Succès : mise à jour de l'historique
            for user_giver, user_gifted in users_history.items():
                data[user_giver]["history"].append(user_gifted)
                logger.debug(f"{user_giver} -> {data[user_giver]['history'][-1]}")

            logger.info(f"Success (attempt:{attempt}, steps:{steps})")
            return True

    logger.error("Error: too much tossing")
    return False


def _configure_logger(filename: str) -> None:
    helper.configure_logger(filename)


if __name__ == "__main__":
    main()
