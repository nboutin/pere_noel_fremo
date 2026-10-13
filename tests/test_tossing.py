import copy
from typing import Any
from unittest.mock import MagicMock

import pytest
from pere_noel_fremo import email_tossing
from pere_noel_fremo.email_annonce import build_parser as build_annonce_parser
from pere_noel_fremo.email_tossing import (
    build_parser as build_tossing_parser,
)
from pere_noel_fremo.email_tossing import (
    tossing,
    validate_lutins_data,
)


@pytest.fixture
def sample_lutins_data() -> dict[str, Any]:
    """Jeu de données minimaliste et contrôlé de Lutins pour tester le tirage au sort."""
    return {
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


def test_tossing_success_respects_all_invariants(sample_lutins_data: dict[str, Any]) -> None:
    data = copy.deepcopy(sample_lutins_data)
    # Sans cheater imposé
    success = tossing(data, cheaters=[])

    assert success is True

    # 1. Chaque Donneur doit avoir exactement un nouveau Bénéficiaire à la fin de son historique
    givers = list(data.keys())
    new_gifted_list = [data[giver]["history"][-1] for giver in givers]

    # Pas d'auto-cadeau
    for giver in givers:
        gifted = data[giver]["history"][-1]
        assert giver != gifted, f"{giver} s'est offert un cadeau à lui-même"

    # Bijections : tous les Lutins reçoivent exactement 1 cadeau
    assert sorted(new_gifted_list) == sorted(givers)
    assert len(set(new_gifted_list)) == len(givers)

    # 2. Respect des exclusions
    for giver in givers:
        gifted = data[giver]["history"][-1]
        assert gifted not in sample_lutins_data[giver]["exclude"], f"{gifted} est dans les exclusions de {giver}"

    # 3. Respect de l'historique permanent (le nouveau gifted ne doit pas être dans l'ancien historique)
    for giver in givers:
        old_history = sample_lutins_data[giver]["history"]
        new_gifted = data[giver]["history"][-1]
        assert new_gifted not in old_history, f"{new_gifted} était déjà dans l'historique de {giver}"


def test_tossing_with_skipped_participant(sample_lutins_data: dict[str, Any]) -> None:
    data = copy.deepcopy(sample_lutins_data)
    to_skip = ["lutin_d"]

    success = tossing(data, to_skip=to_skip, cheaters=[])
    assert success is True

    # lutin_d ne doit ni donner ni recevoir de cadeau
    active_givers = [k for k in data if k not in to_skip]
    for giver in active_givers:
        gifted = data[giver]["history"][-1]
        assert gifted != "lutin_d", "Lutin absent a été choisi comme bénéficiaire"
        assert giver != "lutin_d", "Lutin absent a été choisi comme donneur"

    # lutin_d ne doit pas avoir d'historique mis à jour
    assert len(data["lutin_d"]["history"]) == len(sample_lutins_data["lutin_d"]["history"])


def test_tossing_cheaters_imposed_pairs() -> None:
    """Vérifie que les paires de cheaters définies sont imposées si les membres sont présents."""
    data = {
        "lutin_1": {"fullname": "Lutin 1", "exclude": [], "history": []},
        "lutin_2": {"fullname": "Lutin 2", "exclude": [], "history": []},
        "lutin_3": {"fullname": "Lutin 3", "exclude": [], "history": []},
        "lutin_4": {"fullname": "Lutin 4", "exclude": [], "history": []},
    }
    # On force la paire lutin_1 -> lutin_3
    cheaters = [{"giver": "lutin_1", "gifted": "lutin_3"}]

    success = tossing(data, cheaters=cheaters)
    assert success is True
    assert data["lutin_1"]["history"][-1] == "lutin_3"


def test_tossing_fails_when_no_valid_solution_possible() -> None:
    """Si les exclusions bloquent toutes les possibilités, tossing doit échouer proprement sans crash."""
    impossible_data = {
        "lutin_1": {"fullname": "1", "exclude": ["lutin_2"], "history": []},
        "lutin_2": {"fullname": "2", "exclude": ["lutin_1"], "history": []},
    }
    # Entre 2 personnes qui s'excluent mutuellement, aucun tirage n'est possible
    success = tossing(impossible_data, cheaters=[])
    assert success is False


def test_validate_lutins_data_valid(sample_lutins_data: dict[str, Any]) -> None:
    # Ne doit pas lever d'exception
    validate_lutins_data(sample_lutins_data)


def test_validate_lutins_data_invalid_structure() -> None:
    # 1. Pas un dictionnaire
    with pytest.raises(ValueError, match="dictionnaire non vide"):
        validate_lutins_data([])  # type: ignore[arg-type]

    # 2. Dictionnaire vide
    with pytest.raises(ValueError, match="dictionnaire non vide"):
        validate_lutins_data({})

    # 3. Champ obligatoire manquant
    incomplete_data = {
        "lutin_1": {"fullname": "Lutin 1", "exclude": []}  # manque history
    }
    with pytest.raises(ValueError, match="manque les champs obligatoires"):
        validate_lutins_data(incomplete_data)

    # 4. Exclude ou history n'est pas une liste
    invalid_types = {"lutin_1": {"fullname": "Lutin 1", "exclude": "lutin_2", "history": []}}
    with pytest.raises(ValueError, match="doivent"):
        validate_lutins_data(invalid_types)

    # 5. Exclusion faisant référence à un Lutin inexistant
    unknown_exclude = {"lutin_1": {"fullname": "Lutin 1", "exclude": ["lutin_inconnu"], "history": []}}
    with pytest.raises(ValueError, match="exclusions inconnues"):
        validate_lutins_data(unknown_exclude)


def test_tossing_cli_parser_defaults() -> None:
    parser = build_tossing_parser()
    args = parser.parse_args([])
    assert args.year == 2025
    assert args.skip == []


def test_tossing_cli_parser_custom_args() -> None:
    parser = build_tossing_parser()
    args = parser.parse_args(["--year", "2024", "--skip", "lutin_a,lutin_b"])
    assert args.year == 2024
    assert args.skip == ["lutin_a", "lutin_b"]


def test_annonce_cli_parser_args() -> None:
    parser = build_annonce_parser()
    args = parser.parse_args(["--year", "2023", "--skip", "lutin_x", "--dry-run"])
    assert args.year == 2023
    assert args.skip == ["lutin_x"]
    assert args.dry_run is True


def test_tossing_cli_parser_dry_run_and_no_email() -> None:
    parser = build_tossing_parser()
    args = parser.parse_args(["--dry-run", "--no-email"])
    assert args.dry_run is True
    assert args.no_email is True


def test_tossing_main_dry_run(monkeypatch: pytest.MonkeyPatch, sample_lutins_data: dict[str, Any]) -> None:
    mock_send = MagicMock()
    mock_dump = MagicMock()
    monkeypatch.setattr(email_tossing.helper, "gmail_send_email", mock_send)
    monkeypatch.setattr("yaml.dump", mock_dump)
    monkeypatch.setattr("builtins.open", MagicMock())
    monkeypatch.setattr("yaml.safe_load", lambda stream: copy.deepcopy(sample_lutins_data))

    # Execution en mode dry-run
    email_tossing.main(["--dry-run"])

    # En dry-run, ni envoi d'email ni dump de fichier ne doivent être effectués
    mock_send.assert_not_called()
    mock_dump.assert_not_called()
