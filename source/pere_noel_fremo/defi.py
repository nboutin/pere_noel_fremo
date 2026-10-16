import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .config import resolve_res_dir
from .helper import FRENCH_DAYS, FRENCH_MONTHS

logger = logging.getLogger(__name__)

PARIS_TZ = ZoneInfo("Europe/Paris")

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

ANIMAUX_LUTINS = [
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


# Barème officiel Grand Prix F1 / Mario Kart (1er=10, 2e=8, etc., prime de complétion=1)
POINTS_BAREME = [10, 8, 6, 5, 4, 3, 2, 1]

# Neutralisation de la force brute : seuils officiels (Ticket #29)
MAX_ESSAIS_PAR_MANCHE: int = 3
PENALITE_ESSAI_FAUX_SECONDES: int = 15


def calculate_points_for_rank(rank_1_indexed: int) -> int:
    """Retourne les points attribués pour un rang donné (1er = 10, etc., prime de complétion = 1)."""
    if rank_1_indexed <= 0:
        return 0
    if rank_1_indexed <= len(POINTS_BAREME):
        return POINTS_BAREME[rank_1_indexed - 1]
    return 1


def calculate_manche_points(classement: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attribue les rangs et points selon le barème Grand Prix aux participants ayant résolu la manche."""
    from .parcours import StatutManche, statut_score

    result: list[dict[str, Any]] = []
    solved_rank = 1
    for entry in classement:
        entry_copy = dict(entry)
        statut = statut_score(entry_copy)
        if statut is StatutManche.RESOLUE:
            entry_copy["rank"] = solved_rank
            entry_copy["points"] = calculate_points_for_rank(solved_rank)
            solved_rank += 1
        elif statut is StatutManche.SCELLEE:
            entry_copy["rank"] = None
            entry_copy["points"] = 1
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
        manche_scores = [s for s in manche_scores if s.get("started_at") is not None]
        scored_entries = calculate_manche_points(manche_scores)

        for entry in scored_entries:
            pseudo = str(entry.get("pseudo_lutin") or "")
            lutin_key = str(entry.get("lutin_id") or pseudo)
            if lutin_key not in standings_map:
                standings_map[lutin_key] = {
                    "pseudo_lutin": pseudo,
                    "lutin_id": entry.get("lutin_id"),
                    "total_points": 0,
                    "total_time_seconds": 0.0,
                    "manches_resolved_count": 0,
                    "details": {},
                }

            lutin_entry = standings_map[lutin_key]
            lutin_entry["pseudo_lutin"] = pseudo
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
    # Classement officiel : total_points décroissant, puis départage manches réussies, puis temps cumulé
    standings.sort(
        key=lambda lutin_score: (
            -lutin_score["total_points"],
            -lutin_score["manches_resolved_count"],
            lutin_score["total_time_seconds"],
            lutin_score["pseudo_lutin"],
        )
    )

    for rank_idx, lutin_entry in enumerate(standings, start=1):
        lutin_entry["rank"] = rank_idx

    return standings


def _parse_unlock_at(value: Any) -> datetime:
    """Interprète un unlock_at : naïf -> Europe/Paris, avec décalage explicite -> respecté tel quel."""
    val_str = str(value).strip()
    unlock_dt = datetime.fromisoformat(val_str) if "T" in val_str else datetime.strptime(val_str, "%Y-%m-%d %H:%M:%S")
    if unlock_dt.tzinfo is None:
        unlock_dt = unlock_dt.replace(tzinfo=PARIS_TZ)
    return unlock_dt


def format_unlock_at(value: Any) -> str:
    """Formate un unlock_at en français lisible (« lundi 19 octobre, 19h00 », heure de Paris)."""
    if not value:
        return ""
    try:
        dt = _parse_unlock_at(value).astimezone(PARIS_TZ)
    except Exception:
        return str(value)
    return f"{FRENCH_DAYS[dt.weekday()]} {dt.day} {FRENCH_MONTHS[dt.month - 1]}, {dt.hour}h{dt.minute:02d}"


def is_manche_unlocked(manche: dict[str, Any], now: datetime | None = None) -> bool:
    """Vérifie si une manche est débloquée temporellement (fail-closed si format invalide)."""
    unlock_at_val = manche.get("unlock_at")
    if not unlock_at_val:
        return True

    now_dt = now or datetime.now(timezone.utc)
    try:
        unlock_dt = _parse_unlock_at(unlock_at_val)
        return unlock_dt <= now_dt
    except Exception:
        # En cas d'erreur de parsing, fail-closed par sécurité
        return False


def _lire_manche(file: Path, manche_id: int, now: datetime | None) -> dict[str, Any] | None:
    """Lit un fichier manche_N.yml ; None (avec WARNING sans traceback) s'il est illisible ou n'est pas un dict."""
    try:
        with open(file, encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        if not isinstance(loaded, dict):
            logger.warning("Manche ignorée : fichier %s illisible (contenu non dict)", file.name)
            return None
        data = dict(loaded)
        declared = data.get("id")
        data["id"] = int(manche_id if declared is None else declared)
    except (yaml.YAMLError, OSError, ValueError, TypeError) as exc:
        logger.warning("Manche ignorée : fichier %s illisible (%s: %s)", file.name, type(exc).__name__, exc)
        return None
    data["is_unlocked"] = is_manche_unlocked(data, now=now)
    return data


def get_manche(
    year: int = 2026,
    manche_id: int = 1,
    res_dir: Path | str | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Charge une manche spécifique depuis res/{YEAR}/grilles/manche_{ID}.yml (ou None si introuvable)."""
    base_res = Path(res_dir) if res_dir is not None else resolve_res_dir()
    grilles_dir = base_res / str(year) / "grilles"
    manche_file = grilles_dir / f"manche_{manche_id}.yml"

    data: dict[str, Any]
    if manche_file.exists():
        return _lire_manche(manche_file, manche_id, now)

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
    base_res = Path(res_dir) if res_dir is not None else resolve_res_dir()
    grilles_dir = base_res / str(year) / "grilles"
    now_dt = now or datetime.now(timezone.utc)

    manches: list[dict[str, Any]] = []
    found_files = list(grilles_dir.glob("manche_*.yml")) if grilles_dir.exists() else []

    if found_files:
        for file in sorted(found_files):
            stem = file.stem.replace("manche_", "")
            default_id = int(stem) if stem.isdigit() else len(manches) + 1
            data = _lire_manche(file, default_id, now_dt)
            if data is not None and (not only_unlocked or data["is_unlocked"]):
                manches.append(data)
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


class GrilleInvalideError(ValueError):
    """Grille de manche incohérente (catégories, attributs ou solution contradictoires)."""


def _pluriels_candidats(cle: str) -> set[str]:
    return {f"{cle}s", f"{cle}x"}


def get_manche_attributes(manche: dict[str, Any]) -> list[tuple[str, str]]:
    """Retourne les attributs de la grille sous forme de paires (clé singulière, catégorie plurielle).

    Source : champ explicite `attributs:` (clé singulière -> catégorie plurielle) ou, à défaut,
    dérivation depuis les clés de `solution` rapprochées des catégories hors `lutins`.
    Lève GrilleInvalideError si la grille est ambiguë ou incohérente.
    """
    categories = manche.get("categories")
    solution = manche.get("solution")
    if not isinstance(categories, dict) or not isinstance(solution, dict) or not solution:
        raise GrilleInvalideError("La grille doit définir 'categories' et 'solution'.")

    lutins = categories.get("lutins")
    if not isinstance(lutins, list) or sorted(map(str, lutins)) != sorted(map(str, solution.keys())):
        raise GrilleInvalideError("Les catégories 'lutins' doivent correspondre aux clés de 'solution'.")

    entries = list(solution.values())
    if not all(isinstance(entry, dict) for entry in entries):
        raise GrilleInvalideError("Chaque entrée de 'solution' doit être un dictionnaire d'attributs.")
    solution_keys = list(entries[0].keys())
    if not solution_keys:
        raise GrilleInvalideError("La solution ne définit aucun attribut.")
    if any(set(entry.keys()) != set(solution_keys) for entry in entries):
        raise GrilleInvalideError("Tous les Lutins doivent avoir les mêmes attributs dans 'solution'.")

    explicit = manche.get("attributs")
    attributes: list[tuple[str, str]] = []
    if explicit is not None:
        if not isinstance(explicit, dict) or not explicit:
            raise GrilleInvalideError("'attributs' doit associer chaque clé singulière à une catégorie.")
        attributes = [(str(cle), str(categorie)) for cle, categorie in explicit.items()]
    else:
        autres = [name for name in categories if name != "lutins"]
        for cle in solution_keys:
            candidates = [name for name in autres if name in _pluriels_candidats(str(cle))]
            if len(candidates) != 1:
                raise GrilleInvalideError(f"Impossible de rapprocher l'attribut '{cle}' d'une unique catégorie.")
            attributes.append((str(cle), candidates[0]))

    if sorted(cle for cle, _ in attributes) != sorted(map(str, solution_keys)):
        raise GrilleInvalideError("Les attributs ne correspondent pas aux clés de 'solution'.")
    categories_utilisees = [categorie for _, categorie in attributes]
    if len(set(categories_utilisees)) != len(categories_utilisees):
        raise GrilleInvalideError("Deux attributs ne peuvent pas partager la même catégorie.")

    for cle, categorie in attributes:
        valeurs = categories.get(categorie)
        if not isinstance(valeurs, list) or not valeurs:
            raise GrilleInvalideError(f"La catégorie '{categorie}' de l'attribut '{cle}' est absente.")
        if sorted(entry[cle] for entry in entries) != sorted(valeurs):
            raise GrilleInvalideError(
                f"Les valeurs de '{cle}' ne forment pas une permutation de la catégorie '{categorie}'."
            )
    return attributes


def is_solution_complete(grille: dict[str, Any], solution: dict[str, Any]) -> bool:
    """Vérifie si une grille soumise est complète (tous les attributs de la grille renseignés)."""
    if not isinstance(solution, dict) or not solution:
        return False
    try:
        attributes = get_manche_attributes(grille)
    except GrilleInvalideError:
        return False
    for lutin in grille["categories"]["lutins"]:
        if lutin not in solution:
            return False
        entry = solution[lutin]
        if not isinstance(entry, dict):
            return False
        if any(not entry.get(cle) for cle, _ in attributes):
            return False
    return True


def __getattr__(name: str) -> Any:
    if name == "RES_DIR":
        return resolve_res_dir()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
