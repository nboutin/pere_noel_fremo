import hashlib
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


def get_or_load_grille(year: int = 2026, res_dir: Path | str | None = None) -> dict[str, Any]:
    """Charge la grille logique configurée pour l'année, ou renvoie la grille par défaut."""
    base_res = Path(res_dir) if res_dir is not None else RES_DIR
    grille_file = base_res / str(year) / "defi_grille.yml"

    if grille_file.exists():
        with open(grille_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if isinstance(data, dict):
                return data

    return dict(DEFAULT_GRILLE_2026)


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
