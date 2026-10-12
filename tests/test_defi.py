from datetime import datetime, timezone
from pathlib import Path

from pere_noel_fremo.defi import (
    calculate_points_for_rank,
    generate_pseudo_lugeur,
    get_all_manches,
    get_manche,
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


def test_calculate_points_for_rank() -> None:
    # Barème officiel Grand Prix : [10, 8, 6, 5, 4, 3, 2, 1]
    expected = [10, 8, 6, 5, 4, 3, 2, 1]
    for idx, pts in enumerate(expected, start=1):
        assert calculate_points_for_rank(idx) == pts

    # Au-delà du barème : prime de complétion de 1 point
    assert calculate_points_for_rank(9) == 1
    assert calculate_points_for_rank(25) == 1

    # Rang invalide : 0 point
    assert calculate_points_for_rank(0) == 0
    assert calculate_points_for_rank(-1) == 0


def test_get_manche_loads_configured_grille_or_fallback(tmp_path: Path) -> None:
    # Grille existante dans le dépôt pour 2026
    m1 = get_manche(year=2026, manche_id=1)
    assert m1["id"] == 1
    assert "Les Luges de l'Avent" in m1["title"]
    assert "Barnabé" in m1["categories"]["lutins"]

    m2 = get_manche(year=2026, manche_id=2)
    assert m2["id"] == 2
    assert "La Ronde des Étoiles" in m2["title"]
    assert "Léon" in m2["categories"]["lutins"]

    # Manche inexistante dans un dossier temporaire vide -> repli par défaut
    m_fallback = get_manche(year=2026, manche_id=42, res_dir=tmp_path)
    assert m_fallback["id"] == 42
    assert "categories" in m_fallback


def test_get_all_manches_temporal_unlock() -> None:
    # Manche 1 : unlock 2026-10-16 19:00:00
    # Manche 2 : unlock 2026-10-19 19:00:00

    # 1. Avant le déblocage de la manche 2 (ex: 17 octobre 2026)
    date_avant_m2 = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
    all_m = get_all_manches(year=2026, now=date_avant_m2, only_unlocked=False)
    assert len(all_m) >= 2
    m1 = next(m for m in all_m if m["id"] == 1)
    m2 = next(m for m in all_m if m["id"] == 2)
    assert m1["is_unlocked"] is True
    assert m2["is_unlocked"] is False

    # Filtrage only_unlocked=True
    unlocked_only = get_all_manches(year=2026, now=date_avant_m2, only_unlocked=True)
    unlocked_ids = [m["id"] for m in unlocked_only]
    assert 1 in unlocked_ids
    assert 2 not in unlocked_ids

    # 2. Après le déblocage de la manche 2 (ex: 20 octobre 2026)
    date_apres_m2 = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    all_m_apres = get_all_manches(year=2026, now=date_apres_m2, only_unlocked=True)
    apres_ids = [m["id"] for m in all_m_apres]
    assert 1 in apres_ids
    assert 2 in apres_ids


def test_validate_grille_solution_on_manche_2() -> None:
    m2 = get_manche(year=2026, manche_id=2)
    assert validate_grille_solution(m2, m2["solution"]) is True


def test_calculate_manche_points_awards_grand_prix_points() -> None:
    from pere_noel_fremo.defi import calculate_manche_points

    classement = [
        {"pseudo_lugeur": "Lutin Rapide", "solved": 1, "time_seconds": 22.1},
        {"pseudo_lugeur": "Renne Agile", "solved": 1, "time_seconds": 35.4},
        {"pseudo_lugeur": "Pingouin Lent", "solved": 0, "time_seconds": None},
    ]
    attributed = calculate_manche_points(classement)

    assert len(attributed) == 3
    # 1er résolu
    assert attributed[0]["pseudo_lugeur"] == "Lutin Rapide"
    assert attributed[0]["rank"] == 1
    assert attributed[0]["points"] == 10

    # 2e résolu
    assert attributed[1]["pseudo_lugeur"] == "Renne Agile"
    assert attributed[1]["rank"] == 2
    assert attributed[1]["points"] == 8

    # Non résolu
    assert attributed[2]["pseudo_lugeur"] == "Pingouin Lent"
    assert attributed[2]["rank"] is None
    assert attributed[2]["points"] == 0


def test_is_manche_unlocked_fail_closed_on_invalid_date() -> None:
    from pere_noel_fremo.defi import is_manche_unlocked

    # Format de date corrompu -> fail-closed (False)
    assert is_manche_unlocked({"unlock_at": "invalid-date-format"}) is False

    # Date future -> False
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    assert is_manche_unlocked({"unlock_at": "2099-12-31 19:00:00"}, now=datetime.now(timezone.utc)) is False

    # Date passée -> True
    assert is_manche_unlocked({"unlock_at": "2020-01-01 19:00:00"}, now=future) is True

    # Pas d'attribut unlock_at -> True par défaut
    assert is_manche_unlocked({}) is True


def test_all_15_manches_calendar_integration() -> None:
    # Avant le coup d'envoi du championnat (1er octobre 2026) : 0 manche débloquée
    pre_season = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    unlocked_pre = get_all_manches(year=2026, now=pre_season, only_unlocked=True)
    assert len(unlocked_pre) == 0

    # Après la fin du réveillon (10 décembre 2026) : les 15 manches sont débloquées
    post_season = datetime(2026, 12, 10, 12, 0, 0, tzinfo=timezone.utc)
    all_15 = get_all_manches(year=2026, now=post_season, only_unlocked=True)
    assert len(all_15) == 15
    assert [m["id"] for m in all_15] == list(range(1, 16))
