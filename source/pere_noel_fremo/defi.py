import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RES_DIR = PROJECT_ROOT / "res"

ADJECTIFS_FESTIFS = [
    "Givré",
    "Agile",
    "Fringant",
    "Étoilé",
    "Joyeux",
    "Malicieux",
    "Intrépide",
    "Flamboyant",
    "Rapide",
    "Scintillant",
    "Pétillant",
    "Polaire",
    "Magique",
    "Doré",
    "Argenté",
]

ANIMAUX_LUGEURS = [
    "Lutin",
    "Renne",
    "Pingouin",
    "Ours",
    "Bonhomme",
    "Cerf",
    "Elfe",
    "Husky",
    "Marmotte",
    "Flocon",
    "Écureuil",
    "Lièvre",
]

DEFAULT_GRILLE_2026: dict[str, Any] = {
    "title": "Le Défi du lutin malin",
    "description": "Retrouve quel Lutin conduit quelle luge et apporte quelle friandise !",
    "estimated_time": "2 à 5 minutes",
    "categories": {
        "lutins": ["Barnabé", "Clémence", "Gaspard"],
        "luges": ["Étoile Rouge", "Comète Bleue", "Éclair Vert"],
        "friandises": ["Pain d'épices", "Canne de sucre", "Chocolat chaud"],
    },
    "indices": [
        "Le pilote de la Comète Bleue adore le Chocolat chaud.",
        "Barnabé ne conduit pas l'Étoile Rouge.",
        "Celui qui apporte la Canne de sucre pilote l'Éclair Vert.",
        "Clémence raffole du Pain d'épices.",
    ],
    "solution": {
        "Barnabé": {"luge": "Comète Bleue", "friandise": "Chocolat chaud"},
        "Clémence": {"luge": "Étoile Rouge", "friandise": "Pain d'épices"},
        "Gaspard": {"luge": "Éclair Vert", "friandise": "Canne de sucre"},
    },
}


def generate_pseudo_lugeur(lutin_id: str, year: int) -> str:
    """Génère de façon pseudo-aléatoire mais stable et déterministe un Pseudo de lugeur festif."""
    seed = f"fremo_luge:{year}:{lutin_id}".encode()
    digest = hashlib.sha256(seed).hexdigest()

    idx_animal = int(digest[:8], 16) % len(ANIMAUX_LUGEURS)
    idx_adjectif = int(digest[8:16], 16) % len(ADJECTIFS_FESTIFS)

    return f"{ANIMAUX_LUGEURS[idx_animal]} {ADJECTIFS_FESTIFS[idx_adjectif]}"


# Alias conforme au GLOSSARY (Pseudo de lutin)
generate_pseudo_lutin = generate_pseudo_lugeur

# Barème officiel Grand Prix F1 / Mario Kart (1er=10, 2e=8, etc., prime de complétion=1)
POINTS_BAREME = [10, 8, 6, 5, 4, 3, 2, 1]


def calculate_points_for_rank(rank_1_indexed: int) -> int:
    """Retourne les points attribués pour un rang donné (1er = 10, etc., prime de complétion = 1)."""
    if rank_1_indexed <= 0:
        return 0
    if rank_1_indexed <= len(POINTS_BAREME):
        return POINTS_BAREME[rank_1_indexed - 1]
    return 1


def calculate_manche_points(classement: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attribue les rangs et points selon le barème Grand Prix aux participants ayant résolu la manche."""
    result: list[dict[str, Any]] = []
    solved_rank = 1
    for entry in classement:
        entry_copy = dict(entry)
        if entry_copy.get("solved"):
            entry_copy["rank"] = solved_rank
            entry_copy["points"] = calculate_points_for_rank(solved_rank)
            solved_rank += 1
        else:
            entry_copy["rank"] = None
            entry_copy["points"] = 0
        result.append(entry_copy)
    return result


def calculate_championship_standings(
    db_path: Path | str,
    year: int,
    res_dir: Path | str | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Calcule le classement général du championnat en agrégeant les points et temps des manches débloquées."""
    from .database import get_scores_classement

    unlocked_manches = get_all_manches(year=year, res_dir=res_dir, now=now, only_unlocked=True)
    if not unlocked_manches:
        return []

    standings_map: dict[str, dict[str, Any]] = {}

    for manche in unlocked_manches:
        manche_id = int(manche["id"])
        manche_scores = get_scores_classement(db_path, year, manche_id=manche_id)
        scored_entries = calculate_manche_points(manche_scores)

        for entry in scored_entries:
            pseudo = str(entry["pseudo_lugeur"])
            if pseudo not in standings_map:
                standings_map[pseudo] = {
                    "pseudo_lutin": pseudo,
                    "pseudo_lugeur": pseudo,
                    "total_points": 0,
                    "total_time_seconds": 0.0,
                    "manches_resolved_count": 0,
                    "details": {},
                }

            lutin_entry = standings_map[pseudo]
            points = int(entry.get("points", 0))
            lutin_entry["total_points"] += points

            if entry.get("solved") and entry.get("time_seconds") is not None:
                lutin_entry["total_time_seconds"] += float(entry["time_seconds"])
                lutin_entry["manches_resolved_count"] += 1

            lutin_entry["details"][manche_id] = {
                "solved": bool(entry.get("solved")),
                "time_seconds": entry.get("time_seconds"),
                "rank": entry.get("rank"),
                "points": points,
            }

    standings = list(standings_map.values())
    # Classement officiel : total_points décroissant, puis départage au temps cumulé croissant
    standings.sort(
        key=lambda lutin_score: (
            -lutin_score["total_points"],
            lutin_score["total_time_seconds"],
            -lutin_score["manches_resolved_count"],
            lutin_score["pseudo_lutin"],
        )
    )

    for rank_idx, lutin_entry in enumerate(standings, start=1):
        lutin_entry["rank"] = rank_idx

    return standings


def is_manche_unlocked(manche: dict[str, Any], now: datetime | None = None) -> bool:
    """Vérifie si une manche est débloquée temporellement (fail-closed si format invalide)."""
    unlock_at_val = manche.get("unlock_at")
    if not unlock_at_val:
        return True

    now_dt = now or datetime.now(timezone.utc)
    try:
        val_str = str(unlock_at_val).strip()
        if "T" in val_str:
            unlock_dt = datetime.fromisoformat(val_str)
        else:
            unlock_dt = datetime.strptime(val_str, "%Y-%m-%d %H:%M:%S")

        if unlock_dt.tzinfo is None:
            unlock_dt = unlock_dt.replace(tzinfo=timezone.utc)

        return unlock_dt <= now_dt
    except Exception:
        # En cas d'erreur de parsing, fail-closed par sécurité
        return False


def get_manche(
    year: int = 2026,
    manche_id: int = 1,
    res_dir: Path | str | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Charge une manche spécifique depuis res/{YEAR}/grilles/manche_{ID}.yml (ou None si introuvable)."""
    base_res = Path(res_dir) if res_dir is not None else RES_DIR
    grilles_dir = base_res / str(year) / "grilles"
    manche_file = grilles_dir / f"manche_{manche_id}.yml"

    data: dict[str, Any]
    if manche_file.exists():
        with open(manche_file, encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                data = dict(loaded)
                data.setdefault("id", manche_id)
                data["is_unlocked"] = is_manche_unlocked(data, now=now)
                return data

    # Repli sur l'ancien fichier defi_grille.yml ou DEFAULT_GRILLE_2026 pour la manche 1
    if manche_id == 1:
        grille_file = base_res / str(year) / "defi_grille.yml"
        if grille_file.exists():
            with open(grille_file, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    data = dict(loaded)
                    data.setdefault("id", 1)
                    data["is_unlocked"] = is_manche_unlocked(data, now=now)
                    return data

        fallback = dict(DEFAULT_GRILLE_2026)
        fallback["id"] = 1
        fallback["is_unlocked"] = True
        return fallback

    return None


def get_all_manches(
    year: int = 2026,
    res_dir: Path | str | None = None,
    now: datetime | None = None,
    only_unlocked: bool = False,
) -> list[dict[str, Any]]:
    """Charge toutes les manches configurées pour une édition, triées par id, avec état de déblocage."""
    base_res = Path(res_dir) if res_dir is not None else RES_DIR
    grilles_dir = base_res / str(year) / "grilles"
    now_dt = now or datetime.now(timezone.utc)

    manches: list[dict[str, Any]] = []
    found_files = list(grilles_dir.glob("manche_*.yml")) if grilles_dir.exists() else []

    if found_files:
        for file in sorted(found_files):
            try:
                with open(file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        manche_num = data.get("id")
                        if manche_num is None:
                            stem = file.stem.replace("manche_", "")
                            manche_num = int(stem) if stem.isdigit() else len(manches) + 1
                        data["id"] = int(manche_num)
                        data["is_unlocked"] = is_manche_unlocked(data, now=now_dt)

                        if not only_unlocked or data["is_unlocked"]:
                            manches.append(data)
            except (yaml.YAMLError, OSError, ValueError, KeyError):
                pass
    else:
        # Aucune grille configurée sur disque : repli sur manche 1 par défaut
        default_manche = get_manche(year=year, manche_id=1, res_dir=base_res, now=now_dt)
        if default_manche is not None and (not only_unlocked or default_manche.get("is_unlocked", True)):
            manches.append(default_manche)

    manches.sort(key=lambda m: int(m.get("id", 0)))
    return manches


def get_or_load_grille(year: int = 2026, res_dir: Path | str | None = None) -> dict[str, Any]:
    """Rétro-compatibilité : charge la première grille (manche 1)."""
    manche = get_manche(year=year, manche_id=1, res_dir=res_dir)
    return manche if manche is not None else dict(DEFAULT_GRILLE_2026)


def validate_grille_solution(grille: dict[str, Any], solution_soumise: dict[str, Any]) -> bool:
    """Vérifie si la solution soumise par le Lutin correspond exactement à la solution de la grille."""
    expected = grille.get("solution") or {}
    if not isinstance(solution_soumise, dict) or not solution_soumise:
        return False

    for key, expected_val in expected.items():
        if key not in solution_soumise:
            return False
        if solution_soumise[key] != expected_val:
            return False

    return True
