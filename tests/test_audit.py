import re
from pathlib import Path

import pytest
from pere_noel_fremo.audit import AuditResult, audit_tirage
from pere_noel_fremo.cli import main
from pere_noel_fremo.database import (
    get_db_connection,
    init_db,
    save_attributions,
    set_lutin_presence,
)

YEAR = 2026
RING = {"l1": "l2", "l2": "l3", "l3": "l4", "l4": "l1"}


def _seed(
    tmp_path: Path,
    *,
    confirmed: tuple[str, ...] = ("l1", "l2", "l3", "l4"),
    exclusions: tuple[tuple[str, str], ...] = (),
    past: tuple[tuple[str, str], ...] = (),
    attributions: dict[str, str] | None = None,
) -> Path:
    """Base tmp_path avec 4 Lutins et des attributions injectées directement (sans passer par le solveur)."""
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2025, 'drawn');")
        conn.execute("INSERT INTO editions (year, status) VALUES (?, 'draft');", (YEAR,))
        for lutin_id in ("l1", "l2", "l3", "l4"):
            conn.execute(
                "INSERT INTO lutins (id, fullname, email) VALUES (?, ?, ?);",
                (lutin_id, lutin_id.upper(), f"{lutin_id}@fremo.org"),
            )
        for donneur, excluded in exclusions:
            conn.execute("INSERT INTO exclusions (lutin_id, excluded_lutin_id) VALUES (?, ?);", (donneur, excluded))
        for donneur, beneficiaire in past:
            conn.execute(
                "INSERT INTO attributions (donneur_id, beneficiaire_id, year, order_index) VALUES (?, ?, 2025, 0);",
                (donneur, beneficiaire),
            )
    conn.close()
    for lutin_id in confirmed:
        set_lutin_presence(db_path, lutin_id, YEAR, present=True)
    save_attributions(db_path, YEAR, RING if attributions is None else attributions)
    return db_path


def _audit(db_path: Path) -> AuditResult:
    return audit_tirage(db_path, YEAR)


def test_audit_valid_ring(tmp_path: Path) -> None:
    result = _audit(_seed(tmp_path))
    assert result.is_valid is True
    assert result.errors == []
    assert result.total_lutins == 4
    assert result.total_participants == 4
    assert result.attributions_count == 4


def test_audit_no_confirmed_lutin(tmp_path: Path) -> None:
    result = _audit(_seed(tmp_path, confirmed=(), attributions={}))
    assert result.is_valid is False
    assert any("Aucun Lutin confirmé" in err for err in result.errors)


def test_audit_unconfirmed_donneur(tmp_path: Path) -> None:
    result = _audit(_seed(tmp_path, confirmed=("l2", "l3", "l4")))
    assert result.is_valid is False
    assert any("Donneurs non confirmés" in err and "l1" in err for err in result.errors)


def test_audit_unconfirmed_beneficiaire(tmp_path: Path) -> None:
    result = _audit(_seed(tmp_path, confirmed=("l1", "l3", "l4")))
    assert result.is_valid is False
    assert any("Bénéficiaires non confirmés" in err and "l2" in err for err in result.errors)


def test_audit_confirmed_lutin_without_donation_or_gift(tmp_path: Path) -> None:
    result = _audit(_seed(tmp_path, attributions={"l1": "l2", "l2": "l3", "l3": "l1"}))
    assert result.is_valid is False
    assert any("sans attribution de don" in err and "l4" in err for err in result.errors)
    assert any("sans attribution de cadeau" in err and "l4" in err for err in result.errors)


def test_audit_non_bijection(tmp_path: Path) -> None:
    result = _audit(_seed(tmp_path, attributions={"l1": "l3", "l2": "l3", "l3": "l1", "l4": "l1"}))
    assert result.is_valid is False
    assert any("Non-bijection" in err for err in result.errors)


def test_audit_self_gift(tmp_path: Path) -> None:
    result = _audit(_seed(tmp_path, attributions={"l1": "l1", "l2": "l3", "l3": "l4", "l4": "l2"}))
    assert result.is_valid is False
    assert any("Auto-cadeau" in err and "l1" in err for err in result.errors)


def test_audit_exclusion_violation(tmp_path: Path) -> None:
    result = _audit(_seed(tmp_path, exclusions=(("l1", "l2"),)))
    assert result.is_valid is False
    assert any("Violation d'exclusion" in err and "l1" in err and "l2" in err for err in result.errors)


def test_audit_history_violation(tmp_path: Path) -> None:
    result = _audit(_seed(tmp_path, past=(("l1", "l2"),)))
    assert result.is_valid is False
    assert any("Violation d'historique" in err and "l1" in err and "l2" in err for err in result.errors)


def test_audit_graph_deadlock(tmp_path: Path) -> None:
    result = _audit(_seed(tmp_path, exclusions=(("l1", "l2"), ("l1", "l3"), ("l1", "l4"))))
    assert result.is_valid is False
    assert any("Impasse de graphe" in err and "l1" in err for err in result.errors)


def test_audit_critical_constraint_is_a_warning(tmp_path: Path) -> None:
    result = _audit(_seed(tmp_path, exclusions=(("l1", "l3"), ("l1", "l4"))))
    assert result.is_valid is True
    assert any("Contrainte critique" in warn and "l1" in warn and "l2" in warn for warn in result.warnings)


def test_cli_audit_tirage_invalid_prints_errors_and_warnings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = _seed(tmp_path, exclusions=(("l1", "l2"), ("l1", "l3")))

    ret = main(["audit-tirage", "--db-path", str(db_path), "--year", str(YEAR)])

    out = capsys.readouterr().out
    assert ret == 1
    assert "INVALIDE" in out
    assert "Erreurs détectées" in out
    assert "Violation d'exclusion" in out
    assert "Avertissements" in out
    assert "Contrainte critique" in out


def test_cli_audit_tirage_valid_reveals_no_donneur_beneficiaire_pair(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = _seed(tmp_path, attributions={})
    assert main(["tirage", "--db-path", str(db_path), "--year", str(YEAR), "--force-retirage"]) == 0
    capsys.readouterr()

    ret = main(["audit-tirage", "--db-path", str(db_path), "--year", str(YEAR)])

    out = capsys.readouterr().out
    assert ret == 0
    assert "VALIDE" in out
    assert not re.search(r"\bl[1-4]\b", out)
    assert "->" not in out
