from pathlib import Path
from typing import Any

import pytest
from pere_noel_fremo.audit import (
    AuditResult,
    audit_tirage,
)
from pere_noel_fremo.database import (
    get_db_connection,
    get_edition_status,
    import_yaml_data,
    init_db,
    save_attributions,
    set_edition_status,
    set_lutin_presence,
)
from pere_noel_fremo.tirage import (
    run_tirage,
    solve_tirage,
)


@pytest.fixture
def test_db_setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    import yaml

    sample_data: dict[str, Any] = {
        "lutin_1": {
            "fullname": "Lutin Un",
            "email": None,
            "exclude": ["lutin_2"],
            "history": [],
        },
        "lutin_2": {
            "fullname": "Lutin Deux",
            "email": None,
            "exclude": ["lutin_1"],
            "history": [],
        },
        "lutin_3": {
            "fullname": "Lutin Trois",
            "email": None,
            "exclude": [],
            "history": [],
        },
        "lutin_4": {
            "fullname": "Lutin Quatre",
            "email": None,
            "exclude": [],
            "history": [],
        },
        "lutin_5": {
            "fullname": "Lutin Cinq",
            "email": None,
            "exclude": [],
            "history": [],
        },
    }
    sample_secure = {
        "personnes": {
            "lutin_1": {"email": "l1@fremo.org"},
            "lutin_2": {"email": "l2@fremo.org"},
            "lutin_3": {"email": "l3@fremo.org"},
            "lutin_4": {"email": "l4@fremo.org"},
            "lutin_5": {"email": "l5@fremo.org"},
        }
    }

    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)

    import_yaml_data(db_path, data_in_path, secure_data_path, year=2026)

    return db_path, data_in_path, secure_data_path


def test_tirage_only_draws_confirmed_lutins(test_db_setup: tuple[Path, Path, Path]) -> None:
    db_path, _, _ = test_db_setup
    year = 2026

    # Seuls lutin_1, lutin_2, lutin_3, lutin_4 confirment leur présence (lutin_5 absent)
    set_lutin_presence(db_path, "lutin_1", year, present=True)
    set_lutin_presence(db_path, "lutin_2", year, present=True)
    set_lutin_presence(db_path, "lutin_3", year, present=True)
    set_lutin_presence(db_path, "lutin_4", year, present=True)
    set_lutin_presence(db_path, "lutin_5", year, present=False)

    result = run_tirage(db_path=db_path, year=year, cheaters=[])
    assert result.success is True
    assert len(result.attributions) == 4
    assert "lutin_5" not in result.attributions
    assert "lutin_5" not in result.attributions.values()


def test_audit_tirage_detects_bijection_and_constraint_violations(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l1', 'L1', 'l1@fremo.org');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l2', 'L2', 'l2@fremo.org');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l3', 'L3', 'l3@fremo.org');")
        # l1 excludes l2
        conn.execute("INSERT INTO exclusions (lutin_id, excluded_lutin_id) VALUES ('l1', 'l2');")
        # l1 history has l3
        conn.execute(
            "INSERT INTO attributions (donneur_id, beneficiaire_id, year, order_index) VALUES ('l1', 'l3', NULL, 0);"
        )
    conn.close()

    set_lutin_presence(db_path, "l1", 2026, present=True)
    set_lutin_presence(db_path, "l2", 2026, present=True)
    set_lutin_presence(db_path, "l3", 2026, present=True)

    # 1. Attribution invalide : violation d'exclusion
    bad_attributions = {
        "l1": "l2",
        "l2": "l3",
        "l3": "l1",
    }
    save_attributions(db_path, 2026, bad_attributions)

    audit: AuditResult = audit_tirage(db_path, year=2026)
    assert audit.is_valid is False
    assert any("exclusion" in err.lower() for err in audit.errors)


def test_tirage_admin_aveugle_masks_summary_and_logs(
    test_db_setup: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    db_path, _, _ = test_db_setup
    year = 2026

    # 4 présents
    set_lutin_presence(db_path, "lutin_1", year, present=True)
    set_lutin_presence(db_path, "lutin_2", year, present=True)
    set_lutin_presence(db_path, "lutin_3", year, present=True)
    set_lutin_presence(db_path, "lutin_4", year, present=True)

    # Organisateur = lutin_1
    with caplog.at_level("INFO"):
        result = run_tirage(
            db_path=db_path,
            year=year,
            organizer_id="lutin_1",
            cheaters=[],
        )
    assert result.success is True

    # Audit valid
    audit = audit_tirage(db_path, year=year)
    assert audit.is_valid is True

    # Vérifier que le format masqué contient *** SECRET *** et ne divulgue ni le Donneur de l'organisateur ni les paires
    masked_summary = result.get_masked_summary(organizer_id="lutin_1")
    assert "*** SECRET ***" in masked_summary
    assert "lutin_1 ->" not in masked_summary
    assert "-> lutin_1" not in masked_summary

    # Vérifier qu'aucun log INFO ou WARNING ne divulgue une paire
    for record in caplog.records:
        assert "->" not in record.message


def test_tirage_respects_cheaters(test_db_setup: tuple[Path, Path, Path]) -> None:
    db_path, _, _ = test_db_setup
    year = 2026

    set_lutin_presence(db_path, "lutin_1", year, present=True)
    set_lutin_presence(db_path, "lutin_2", year, present=True)
    set_lutin_presence(db_path, "lutin_3", year, present=True)
    set_lutin_presence(db_path, "lutin_4", year, present=True)
    set_lutin_presence(db_path, "lutin_5", year, present=True)

    # Imposer une paire cheater lutin_3 -> lutin_4
    cheaters = [{"giver": "lutin_3", "gifted": "lutin_4"}]
    result = run_tirage(db_path=db_path, year=year, cheaters=cheaters)

    assert result.success is True
    assert result.attributions["lutin_3"] == "lutin_4"

    audit = audit_tirage(db_path, year=year)
    assert audit.is_valid is True


def test_tirage_respects_strict_perpetual_history(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        for i in range(1, 5):
            conn.execute(f"INSERT INTO lutins (id, fullname, email) VALUES ('l{i}', 'L{i}', 'l{i}@fremo.org');")
        # Historique strict perpétuel : l1 a déjà offert à l2, l3
        conn.execute(
            "INSERT INTO attributions (donneur_id, beneficiaire_id, year, order_index) VALUES ('l1', 'l2', NULL, 0);"
        )
        conn.execute(
            "INSERT INTO attributions (donneur_id, beneficiaire_id, year, order_index) VALUES ('l1', 'l3', NULL, 1);"
        )
    conn.close()

    for i in range(1, 5):
        set_lutin_presence(db_path, f"l{i}", 2026, present=True)

    result = run_tirage(db_path=db_path, year=2026, cheaters=[])
    assert result.success is True
    # l1 ne peut offrir ni à l1 (soi-même), ni à l2 (historique), ni à l3 (historique) => doit impérativement être l4 !
    assert result.attributions["l1"] == "l4"

    audit = audit_tirage(db_path, year=2026)
    assert audit.is_valid is True


def test_solve_tirage_fails_when_impossible() -> None:
    """Si les exclusions bloquent toutes les possibilités, solve_tirage retourne None."""
    impossible_data = {
        "lutin_1": {"fullname": "1", "exclude": ["lutin_2"], "history": []},
        "lutin_2": {"fullname": "2", "exclude": ["lutin_1"], "history": []},
    }
    result = solve_tirage(impossible_data, cheaters=[])
    assert result is None


def test_solve_tirage_invariants() -> None:
    sample_lutins_data = {
        "lutin_a": {
            "fullname": "Lutin A",
            "exclude": ["lutin_b"],
            "history": ["lutin_c"],
        },
        "lutin_b": {
            "fullname": "Lutin B",
            "exclude": ["lutin_a"],
            "history": [],
        },
        "lutin_c": {
            "fullname": "Lutin C",
            "exclude": [],
            "history": ["lutin_a"],
        },
        "lutin_d": {
            "fullname": "Lutin D",
            "exclude": [],
            "history": [],
        },
        "lutin_e": {
            "fullname": "Lutin E",
            "exclude": [],
            "history": [],
        },
    }
    result = solve_tirage(sample_lutins_data, cheaters=[])
    assert result is not None
    givers = list(sample_lutins_data.keys())
    assert len(result) == len(givers)

    # 1. Pas d'auto-cadeau
    for giver, gifted in result.items():
        assert giver != gifted, f"{giver} s'est offert un cadeau à lui-même"

    # 2. Bijection : tous les Lutins reçoivent exactement 1 cadeau
    assert sorted(result.values()) == sorted(givers)
    assert len(set(result.values())) == len(givers)

    # 3. Respect des exclusions
    for giver, gifted in result.items():
        assert gifted not in sample_lutins_data[giver]["exclude"], f"{gifted} est dans les exclusions de {giver}"

    # 4. Respect de l'historique permanent
    for giver, gifted in result.items():
        assert gifted not in sample_lutins_data[giver]["history"], f"{gifted} était déjà dans l'historique de {giver}"


def test_solve_tirage_imposed_cheaters() -> None:
    data = {
        "lutin_1": {"fullname": "Lutin 1", "exclude": [], "history": []},
        "lutin_2": {"fullname": "Lutin 2", "exclude": [], "history": []},
        "lutin_3": {"fullname": "Lutin 3", "exclude": [], "history": []},
        "lutin_4": {"fullname": "Lutin 4", "exclude": [], "history": []},
    }
    cheaters = [{"giver": "lutin_1", "gifted": "lutin_3"}]
    result = solve_tirage(data, cheaters=cheaters)
    assert result is not None
    assert result["lutin_1"] == "lutin_3"


def _confirm_all(db_path: Path, year: int, ids: list[str]) -> None:
    for lutin_id in ids:
        set_lutin_presence(db_path, lutin_id, year, present=True)


def _dump_year(db_path: Path, year: int) -> list[tuple[str, str, int]]:
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT donneur_id, beneficiaire_id, order_index FROM attributions WHERE year = ? ORDER BY donneur_id;",
            (year,),
        ).fetchall()
        return [(r["donneur_id"], r["beneficiaire_id"], r["order_index"]) for r in rows]
    finally:
        conn.close()


def test_second_tirage_without_force_is_refused_and_leaves_db_untouched(
    test_db_setup: tuple[Path, Path, Path],
) -> None:
    db_path, _, _ = test_db_setup
    _confirm_all(db_path, 2026, ["lutin_1", "lutin_2", "lutin_3", "lutin_4", "lutin_5"])

    first = run_tirage(db_path=db_path, year=2026, cheaters=[])
    assert first.success is True
    before = _dump_year(db_path, 2026)

    second = run_tirage(db_path=db_path, year=2026, cheaters=[])
    assert second.success is False
    assert "force" in second.message.lower()
    assert _dump_year(db_path, 2026) == before


def test_second_tirage_refused_when_revealed(test_db_setup: tuple[Path, Path, Path]) -> None:
    db_path, _, _ = test_db_setup
    _confirm_all(db_path, 2026, ["lutin_1", "lutin_2", "lutin_3", "lutin_4"])
    assert run_tirage(db_path=db_path, year=2026, cheaters=[]).success is True
    set_edition_status(db_path, 2026, "revealed")
    before = _dump_year(db_path, 2026)

    result = run_tirage(db_path=db_path, year=2026, cheaters=[])
    assert result.success is False
    assert _dump_year(db_path, 2026) == before


def test_dry_run_allowed_on_drawn_edition_and_writes_nothing(test_db_setup: tuple[Path, Path, Path]) -> None:
    db_path, _, _ = test_db_setup
    _confirm_all(db_path, 2026, ["lutin_1", "lutin_2", "lutin_3", "lutin_4"])
    assert run_tirage(db_path=db_path, year=2026, cheaters=[]).success is True
    before = _dump_year(db_path, 2026)

    result = run_tirage(db_path=db_path, year=2026, cheaters=[], dry_run=True)
    assert result.success is True
    assert _dump_year(db_path, 2026) == before


def test_force_retirage_replaces_whole_year_without_stale_rows(test_db_setup: tuple[Path, Path, Path]) -> None:
    db_path, _, _ = test_db_setup
    _confirm_all(db_path, 2026, ["lutin_1", "lutin_2", "lutin_3", "lutin_4", "lutin_5"])
    assert run_tirage(db_path=db_path, year=2026, cheaters=[]).success is True

    # lutin_5 n'est plus confirmé : sa ligne du premier tirage ne doit pas survivre
    set_lutin_presence(db_path, "lutin_5", 2026, present=False)

    result = run_tirage(db_path=db_path, year=2026, cheaters=[], force=True)
    assert result.success is True

    rows = _dump_year(db_path, 2026)
    assert sorted(r[0] for r in rows) == ["lutin_1", "lutin_2", "lutin_3", "lutin_4"]
    assert sorted(r[1] for r in rows) == ["lutin_1", "lutin_2", "lutin_3", "lutin_4"]
    assert audit_tirage(db_path, year=2026).is_valid is True


def _fake_invalid_pairs_audit(
    confirmed_lutins: dict[str, dict[str, Any]],
    pairs: dict[str, str],
    exclusions: dict[str, list[str]],
    history: dict[str, list[str]],
    **kwargs: object,
) -> AuditResult:
    return AuditResult(
        is_valid=False,
        total_lutins=4,
        errors=["Violation d'exclusion : 'lutin_1' s'est vu attribuer 'lutin_2', qui est exclu."],
        error_categories=["Violation d'exclusion", "Violation d'exclusion", "Auto-cadeau détecté"],
    )


def _forbid_save(*args: object, **kwargs: object) -> None:
    raise AssertionError("save_attributions ne doit pas être appelée quand l'audit est invalide")


def test_invalid_audit_writes_nothing_on_fresh_draw(
    test_db_setup: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from pere_noel_fremo import tirage as tirage_module

    db_path, _, _ = test_db_setup
    _confirm_all(db_path, 2026, ["lutin_1", "lutin_2", "lutin_3", "lutin_4"])
    status_before = get_edition_status(db_path, 2026)
    monkeypatch.setattr(tirage_module, "audit_pairs", _fake_invalid_pairs_audit)
    monkeypatch.setattr(tirage_module, "save_attributions", _forbid_save)

    result = tirage_module.run_tirage(db_path=db_path, year=2026, cheaters=[])

    assert result.success is False
    assert "audit" in result.message.lower()
    assert _dump_year(db_path, 2026) == []
    assert get_edition_status(db_path, 2026) == status_before
    assert get_edition_status(db_path, 2026) != "drawn"
    # catégories affichées, sans identifiant de Lutin
    assert "Violation d'exclusion (x2)" in result.message
    assert "Auto-cadeau détecté" in result.message
    assert "lutin_" not in result.message


def test_invalid_audit_on_force_retirage_leaves_previous_draw_untouched(
    test_db_setup: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from pere_noel_fremo import tirage as tirage_module

    db_path, _, _ = test_db_setup
    _confirm_all(db_path, 2026, ["lutin_1", "lutin_2", "lutin_3", "lutin_4", "lutin_5"])
    assert run_tirage(db_path=db_path, year=2026, cheaters=[]).success is True
    set_edition_status(db_path, 2026, "revealed")
    before = _dump_year(db_path, 2026)
    monkeypatch.setattr(tirage_module, "audit_pairs", _fake_invalid_pairs_audit)
    monkeypatch.setattr(tirage_module, "save_attributions", _forbid_save)

    result = tirage_module.run_tirage(db_path=db_path, year=2026, cheaters=[], force=True)

    assert result.success is False
    assert _dump_year(db_path, 2026) == before
    assert get_edition_status(db_path, 2026) == "revealed"


def test_invalid_audit_without_categories_reports_unspecified(
    test_db_setup: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from pere_noel_fremo import tirage as tirage_module

    db_path, _, _ = test_db_setup
    _confirm_all(db_path, 2026, ["lutin_1", "lutin_2", "lutin_3", "lutin_4"])
    monkeypatch.setattr(
        tirage_module,
        "audit_pairs",
        lambda *args, **kwargs: AuditResult(is_valid=False, total_lutins=4, errors=["x"]),
    )
    result = tirage_module.run_tirage(db_path=db_path, year=2026, cheaters=[])
    assert "non précisées" in result.message
