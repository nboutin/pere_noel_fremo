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
    assert m1 is not None
    assert m1["id"] == 1
    assert "Les Luges de l'Avent" in m1["title"]
    assert "Barnabé" in m1["categories"]["lutins"]

    m2 = get_manche(year=2026, manche_id=2)
    assert m2 is not None
    assert m2["id"] == 2
    assert "La Ronde des Étoiles" in m2["title"]
    assert "Léon" in m2["categories"]["lutins"]

    # Manche inexistante -> None
    m_not_found = get_manche(year=2026, manche_id=42, res_dir=tmp_path)
    assert m_not_found is None


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
    assert m2 is not None
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


def test_calculate_championship_standings_aggregates_points_and_ties(tmp_path: Path) -> None:
    from pere_noel_fremo.database import (
        complete_score_defi,
        get_db_connection,
        get_or_create_score_defi,
        init_db,
    )
    from pere_noel_fremo.defi import calculate_championship_standings

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l1', 'Lutin 1', 'l1@fremo.org');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l2', 'Lutin 2', 'l2@fremo.org');")
    conn.close()

    # Manche 1 : l1=30.0s (1er, 10pts), l2=45.0s (2e, 8pts)
    get_or_create_score_defi(db_path, "l1", 2026, "Renne Agile", manche_id=1)
    complete_score_defi(db_path, "l1", 2026, time_seconds=30.0, manche_id=1)
    get_or_create_score_defi(db_path, "l2", 2026, "Lutin Givré", manche_id=1)
    complete_score_defi(db_path, "l2", 2026, time_seconds=45.0, manche_id=1)

    # Manche 2 : l2=20.0s (1er, 10pts), l1=40.0s (2e, 8pts)
    get_or_create_score_defi(db_path, "l1", 2026, "Renne Agile", manche_id=2)
    complete_score_defi(db_path, "l1", 2026, time_seconds=40.0, manche_id=2)
    get_or_create_score_defi(db_path, "l2", 2026, "Lutin Givré", manche_id=2)
    complete_score_defi(db_path, "l2", 2026, time_seconds=20.0, manche_id=2)

    simulated_now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    standings = calculate_championship_standings(db_path, 2026, now=simulated_now)

    assert len(standings) == 2
    # Égalité aux points (18 chacun) : l2 (45+20=65s) passe devant l1 (30+40=70s) au temps cumulé
    first = standings[0]
    second = standings[1]

    assert first["pseudo_lutin"] == "Lutin Givré"
    assert first["pseudo_lugeur"] == "Lutin Givré"
    assert first["rank"] == 1
    assert first["total_points"] == 18
    assert round(first["total_time_seconds"], 1) == 65.0
    assert first["manches_resolved_count"] == 2

    assert second["pseudo_lutin"] == "Renne Agile"
    assert second["pseudo_lugeur"] == "Renne Agile"
    assert second["rank"] == 2
    assert second["total_points"] == 18
    assert round(second["total_time_seconds"], 1) == 70.0
    assert second["manches_resolved_count"] == 2


def test_anti_brute_force_constants_and_solution_completeness() -> None:
    from pere_noel_fremo.defi import (
        MAX_ESSAIS_PAR_MANCHE,
        PENALITE_ESSAI_FAUX_SECONDES,
        is_solution_complete,
    )

    assert MAX_ESSAIS_PAR_MANCHE == 3
    assert PENALITE_ESSAI_FAUX_SECONDES == 15

    grille = get_or_load_grille(year=2026)

    # Grille vide ou non dict -> False
    assert is_solution_complete(grille, {}) is False
    assert is_solution_complete(grille, None) is False  # type: ignore

    # Grille partielle (un seul lutin) -> False
    partial = {"Barnabé": {"luge": "Comète Bleue", "friandise": "Chocolat chaud"}}
    assert is_solution_complete(grille, partial) is False

    # Grille avec choix manquants (champ vide) -> False
    incomplete_field = {
        "Barnabé": {"luge": "Comète Bleue", "friandise": ""},
        "Clémence": {"luge": "Étoile Rouge", "friandise": "Pain d'épices"},
        "Gaspard": {"luge": "Éclair Vert", "friandise": "Canne de sucre"},
    }
    assert is_solution_complete(grille, incomplete_field) is False

    # Grille complète (valide ou invalide, mais tous les choix sont renseignés) -> True
    assert is_solution_complete(grille, grille["solution"]) is True


def test_calculate_manche_points_participation_and_voluntary_abandon() -> None:
    from pere_noel_fremo.defi import calculate_manche_points

    classement = [
        {"pseudo_lugeur": "Lutin Rapide", "solved": 1, "time_seconds": 22.1, "attempts": 1},
        # Lutin ayant échoué à 3 essais -> 1 point de participation au championnat
        {"pseudo_lugeur": "Lutin Persistant", "solved": 0, "time_seconds": None, "attempts": 3},
        # Lutin ayant abandonné volontairement avant 3 essais -> 0 point
        {"pseudo_lugeur": "Lutin Découragé", "solved": 0, "time_seconds": None, "attempts": 1},
        # Lutin ayant abandonné sans aucun essai -> 0 point
        {"pseudo_lugeur": "Lutin Fantôme", "solved": 0, "time_seconds": None, "attempts": 0},
    ]

    scored = calculate_manche_points(classement)

    # 1er résolu : 10 pts
    assert scored[0]["rank"] == 1
    assert scored[0]["points"] == 10

    # 3 essais faux : 1 point de participation, pas de rang
    assert scored[1]["rank"] is None
    assert scored[1]["points"] == 1

    # Abandon volontaire avec 1 essai : 0 point
    assert scored[2]["rank"] is None
    assert scored[2]["points"] == 0

    # Abandon sans essai : 0 point
    assert scored[3]["rank"] is None
    assert scored[3]["points"] == 0


def test_championship_standings_tie_breaker_resolved_over_failed_attempts(tmp_path: Path) -> None:
    from pere_noel_fremo.database import (
        get_db_connection,
        init_db,
    )
    from pere_noel_fremo.defi import calculate_championship_standings

    db_path = tmp_path / "fremo_tie_breaker.db"
    init_db(db_path)
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l_resolved', 'Lutin Résolu', 'lr@fremo.org');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l_failed', 'Lutin Échoué', 'lf@fremo.org');")
        # Simuler 8 lutins plus rapides pour que l_resolved n'obtienne que 1 pt (rang >= 8)
        for i in range(1, 9):
            conn.execute(
                f"INSERT INTO lutins (id, fullname, email) VALUES ('l_fast_{i}', 'Fast {i}', 'f{i}@fremo.org');"
            )
            conn.execute(
                """
                INSERT INTO scores_defi (
                    lutin_id, year, manche_id, pseudo_lugeur, started_at, solved, time_seconds, completed_at, attempts
                )
                VALUES (?, 2026, 1, ?, '2026-10-14 20:00:00', 1, ?, '2026-10-14 20:01:00', 1);
                """,
                (f"l_fast_{i}", f"Fast Lugeur {i}", 10.0 + i),
            )

        # l_resolved résout en 9e position (temps 120s) -> 1 point, 1 manche résolue
        conn.execute(
            """
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lugeur,
                started_at, solved, time_seconds, completed_at, attempts
            )
            VALUES (
                'l_resolved', 2026, 1, 'Lutin Persévérant',
                '2026-10-14 20:00:00', 1, 120.0, '2026-10-14 20:02:00', 1
            );
            """
        )

        # l_failed échoue à 3 essais -> 1 point de participation, 0 manche résolue, time_seconds=NULL
        conn.execute(
            """
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lugeur,
                started_at, solved, time_seconds, completed_at, attempts
            )
            VALUES (
                'l_failed', 2026, 1, 'Lutin Malchanceux',
                '2026-10-14 20:00:00', 0, NULL, '2026-10-14 20:03:00', 3
            );
            """
        )
    conn.close()

    simulated_now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    standings = calculate_championship_standings(db_path, 2026, now=simulated_now)

    # Trouver les deux lutins à 1 point
    lutin_res = next(s for s in standings if s["pseudo_lugeur"] == "Lutin Persévérant")
    lutin_fail = next(s for s in standings if s["pseudo_lugeur"] == "Lutin Malchanceux")

    assert lutin_res["total_points"] == 1
    assert lutin_res["manches_resolved_count"] == 1

    assert lutin_fail["total_points"] == 1
    assert lutin_fail["manches_resolved_count"] == 0

    # Au départage, le lutin ayant résolu la manche prime sur celui ayant échoué aux 3 essais
    assert lutin_res["rank"] < lutin_fail["rank"]


def test_calculate_championship_standings_aggregates_by_lutin_id(tmp_path: Path) -> None:
    from pere_noel_fremo.database import (
        get_db_connection,
        init_db,
    )
    from pere_noel_fremo.defi import calculate_championship_standings

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('jdenis', 'Jean Denis', 'jd@fremo.org');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('mdenis', 'Marc Denis', 'md@fremo.org');")
        # Simuler deux lutins résolvant la manche 1 (30s vs 45s)
        conn.execute(
            """
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lugeur, started_at, solved, time_seconds, completed_at, attempts
            )
            VALUES ('jdenis', 2026, 1, 'Lutin A', '2026-10-14 20:00:00', 1, 30.0, '2026-10-14 20:00:30', 1);
            """
        )
        conn.execute(
            """
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lugeur, started_at, solved, time_seconds, completed_at, attempts
            )
            VALUES ('mdenis', 2026, 1, 'Lutin B', '2026-10-14 20:00:00', 1, 45.0, '2026-10-14 20:00:45', 1);
            """
        )
    conn.close()

    simulated_now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    standings = calculate_championship_standings(db_path, 2026, now=simulated_now)

    assert len(standings) == 2
    # Doit contenir lutin_id
    first = standings[0]
    second = standings[1]

    assert first["lutin_id"] == "jdenis"
    assert first["total_points"] == 10
    assert first["rank"] == 1

    assert second["lutin_id"] == "mdenis"
    assert second["total_points"] == 8
    assert second["rank"] == 2
