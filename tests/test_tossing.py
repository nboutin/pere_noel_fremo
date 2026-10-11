import copy
from typing import Any

import pytest
from pere_noel_fremo.email_tossing import tossing


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
