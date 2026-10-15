from pathlib import Path
from typing import Any

import yaml

from .database import get_attributions, get_db_connection


def build_edition_export_data(db_path: Path | str, year: int) -> dict[str, dict[str, Any]]:
    """Construit la structure de données d'archive de clôture de l'Édition au format attendu par data_out.yml.

    Format pour chaque Lutin actif (clés ordonnées alphabétiquement) :
      - email: null
      - exclude: liste des identifiants des lutins exclus (ordre alphabétique)
      - fullname: nom complet du lutin
      - history: liste ordonnée des anciens bénéficiaires se terminant par le bénéficiaire de l'édition courante
    """
    conn = get_db_connection(db_path)
    try:
        # 1. Lutins actifs triés par id
        lutins_rows = conn.execute("SELECT id, fullname FROM lutins WHERE is_active = 1 ORDER BY id ASC;").fetchall()

        # 2. Exclusions triées
        exclusions_rows = conn.execute(
            "SELECT lutin_id, excluded_lutin_id FROM exclusions ORDER BY excluded_lutin_id ASC;"
        ).fetchall()
        exclusions_map: dict[str, list[str]] = {}
        for row in exclusions_rows:
            exclusions_map.setdefault(row["lutin_id"], []).append(row["excluded_lutin_id"])

        # 3. Attributions de l'année courante
        current_attributions = get_attributions(db_path, year)

        # 4. Historique passé (hors année courante)
        past_rows = conn.execute(
            """
            SELECT donneur_id, beneficiaire_id
            FROM attributions
            WHERE year != ? OR year IS NULL
            ORDER BY order_index ASC, id ASC;
            """,
            (year,),
        ).fetchall()
        past_history_map: dict[str, list[str]] = {}
        for row in past_rows:
            past_history_map.setdefault(row["donneur_id"], []).append(row["beneficiaire_id"])

        export_data: dict[str, dict[str, Any]] = {}
        for row in lutins_rows:
            lutin_id = row["id"]
            past_history = past_history_map.get(lutin_id, [])

            # Déduplication de l'historique tout en préservant l'ordre
            history: list[str] = []
            for b_id in past_history:
                if b_id not in history:
                    history.append(b_id)

            # Ajout du Bénéficiaire de l'édition courante en fin d'historique
            current_beneficiaire = current_attributions.get(lutin_id)
            if current_beneficiaire:
                if current_beneficiaire in history:
                    history.remove(current_beneficiaire)
                history.append(current_beneficiaire)

            export_data[lutin_id] = {
                "email": None,
                "exclude": exclusions_map.get(lutin_id, []),
                "fullname": row["fullname"],
                "history": history,
            }

        return export_data
    finally:
        conn.close()


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
