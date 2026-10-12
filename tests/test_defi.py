from pathlib import Path

from pere_noel_fremo.defi import (
    generate_pseudo_lugeur,
    get_or_load_grille,
    validate_grille_solution,
)


def test_generate_pseudo_lugeur_is_deterministic_and_festive() -> None:
    # Doit être stable pour un lutin et une année donnés
    p1 = generate_pseudo_lugeur("lutin_1", 2026)
    p2 = generate_pseudo_lugeur("lutin_1", 2026)
    assert p1 == p2
    assert isinstance(p1, str)
    assert len(p1.split()) >= 2  # ex: "Lutin Givré"

    # Deux lutins différents ont des pseudos différents
    p3 = generate_pseudo_lugeur("lutin_2", 2026)
    assert p1 != p3


def test_get_or_load_grille_provides_default_festive_grid(tmp_path: Path) -> None:
    # Même sans fichier existant sur disque, charge une grille logique cohérente
    grille = get_or_load_grille(year=2026, res_dir=tmp_path)
    assert "categories" in grille
    assert "indices" in grille
    assert "solution" in grille
    assert len(grille["indices"]) >= 3
    assert "lutins" in grille["categories"]


def test_validate_grille_solution_correct_and_incorrect() -> None:
    grille = get_or_load_grille(year=2026)
    solution = grille["solution"]

    # Solution correcte
    assert validate_grille_solution(grille, solution) is True

    # Solution incorrecte
    corrupted = dict(solution)
    # Echanger deux valeurs
    keys = list(corrupted.keys())
    if len(keys) >= 2:
        corrupted[keys[0]], corrupted[keys[1]] = corrupted[keys[1]], corrupted[keys[0]]
        assert validate_grille_solution(grille, corrupted) is False
