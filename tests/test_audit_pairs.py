"""Tests unitaires de l'audit pur `audit_pairs` (sans base de données)."""

from typing import Any

from pere_noel_fremo.audit import audit_pairs

RING = {"l1": "l2", "l2": "l3", "l3": "l4", "l4": "l1"}


def _lutins(
    ids: tuple[str, ...] = ("l1", "l2", "l3", "l4"),
    exclusions: dict[str, list[str]] | None = None,
    history: dict[str, list[str]] | None = None,
) -> dict[str, dict[str, Any]]:
    exclusions = exclusions or {}
    history = history or {}
    return {i: {"exclude": exclusions.get(i, []), "history": history.get(i, [])} for i in ids}


def test_valid_ring() -> None:
    result = audit_pairs(_lutins(), RING, {}, {})
    assert result.is_valid is True
    assert result.errors == []
    assert result.error_categories == []
    assert result.total_lutins == 4
    assert result.attributions_count == 4


def test_no_confirmed_lutin() -> None:
    result = audit_pairs({}, {}, {}, {})
    assert result.is_valid is False
    assert "Aucun Lutin confirmé présent pour l'édition" in result.error_categories


def test_unconfirmed_donneur() -> None:
    result = audit_pairs(_lutins(("l2", "l3", "l4")), RING, {}, {})
    assert result.is_valid is False
    assert "Donneurs non confirmés présents dans le tirage" in result.error_categories


def test_unconfirmed_beneficiaire() -> None:
    result = audit_pairs(_lutins(("l1", "l3", "l4")), RING, {}, {})
    assert result.is_valid is False
    assert "Bénéficiaires non confirmés présents dans le tirage" in result.error_categories


def test_missing_donneur_and_beneficiaire() -> None:
    result = audit_pairs(_lutins(), {"l1": "l2", "l2": "l3", "l3": "l1"}, {}, {})
    assert result.is_valid is False
    assert "Lutins confirmés sans attribution de don" in result.error_categories
    assert "Lutins confirmés sans attribution de cadeau" in result.error_categories


def test_non_bijection() -> None:
    result = audit_pairs(_lutins(), {"l1": "l3", "l2": "l3", "l3": "l1", "l4": "l1"}, {}, {})
    assert result.is_valid is False
    assert "Non-bijection détectée entre donneurs et bénéficiaires" in result.error_categories


def test_self_gift() -> None:
    result = audit_pairs(_lutins(), {"l1": "l1", "l2": "l3", "l3": "l4", "l4": "l2"}, {}, {})
    assert result.is_valid is False
    assert "Auto-cadeau détecté" in result.error_categories


def test_exclusion_violation() -> None:
    result = audit_pairs(_lutins(), RING, {"l1": ["l2"]}, {})
    assert result.is_valid is False
    assert "Violation d'exclusion" in result.error_categories
    assert any("l1" in e and "l2" in e for e in result.errors)


def test_history_violation_compares_to_past_only() -> None:
    result = audit_pairs(_lutins(), RING, {}, {"l1": ["l2"]})
    assert result.is_valid is False
    assert "Violation d'historique" in result.error_categories


def test_history_without_match_is_valid() -> None:
    result = audit_pairs(_lutins(), RING, {}, {"l1": ["l3"]})
    assert result.is_valid is True


def test_graph_deadlock() -> None:
    lutins = _lutins(exclusions={"l1": ["l2", "l3", "l4"]})
    result = audit_pairs(lutins, RING, {}, {})
    assert result.is_valid is False
    assert "Impasse de graphe : un Lutin n'a aucun Bénéficiaire admissible" in result.error_categories


def test_critical_constraint_is_a_warning() -> None:
    lutins = _lutins(exclusions={"l1": ["l3", "l4"]})
    result = audit_pairs(lutins, RING, {}, {})
    assert result.is_valid is True
    assert any("Contrainte critique" in w and "l1" in w and "l2" in w for w in result.warnings)
