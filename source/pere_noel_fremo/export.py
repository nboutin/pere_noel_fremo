from pathlib import Path
from typing import Any

import yaml

from .database import get_attributions, get_lutins, historique_avant


def build_edition_export_data(db_path: Path | str, year: int) -> dict[str, dict[str, Any]]:
    """Construit la structure de données d'archive de clôture de l'Édition au format attendu par data_out.yml.

    Format pour chaque Lutin actif (clés ordonnées alphabétiquement) :
      - email: null
      - exclude: liste des identifiants des lutins exclus (ordre alphabétique)
      - fullname: nom complet du lutin
      - history: liste ordonnée des anciens bénéficiaires se terminant par le bénéficiaire de l'édition courante
    """
    # 1. Lutins actifs avec leurs exclusions (ordonnés par id ASC)
    active_lutins = get_lutins(db_path, active_only=True)

    # 2. Attributions de l'année courante
    current_attributions = get_attributions(db_path, year)

    # 3. Historique passé (strictement antérieur à l'année courante, ADR-0008)
    past_history_map = historique_avant(db_path, year)

    export_data: dict[str, dict[str, Any]] = {}
    for lutin_id, lutin_info in active_lutins.items():
        # `historique_avant` est déjà sans doublon et trié par millésime
        history = list(past_history_map.get(lutin_id, []))

        # Ajout du Bénéficiaire de l'édition courante en fin d'historique s'il n'y figure pas déjà
        current_beneficiaire = current_attributions.get(lutin_id)
        if current_beneficiaire and current_beneficiaire not in history:
            history.append(current_beneficiaire)

        export_data[lutin_id] = {
            "email": None,
            "exclude": lutin_info.get("exclude", []),
            "fullname": lutin_info["fullname"],
            "history": history,
        }

    return export_data


def export_edition_yaml(
    db_path: Path | str,
    year: int,
    output_path: Path | str,
    overwrite: bool = False,
) -> Path:
    """Exporte les attributions et l'historique complet d'une Édition dans un fichier YAML d'archive."""
    target = Path(output_path)
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"Le fichier d'export '{target}' existe déjà. Utilisez l'option --overwrite pour le remplacer."
        )

    data = build_edition_export_data(db_path, year)
    target.parent.mkdir(parents=True, exist_ok=True)

    with open(target, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=True)

    return target
