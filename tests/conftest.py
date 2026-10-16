from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pere_noel_fremo.campagne import ExpediteurMemoire


@pytest.fixture
def expediteur_memoire() -> Iterator[ExpediteurMemoire]:
    """Remplace l'adaptateur Gmail par un ExpediteurMemoire pour les campagnes lancées via la CLI."""
    expediteur = ExpediteurMemoire()
    with (
        patch("pere_noel_fremo.annonce.ExpediteurGmail", return_value=expediteur),
        patch("pere_noel_fremo.revelation.ExpediteurGmail", return_value=expediteur),
    ):
        yield expediteur


@pytest.fixture
def solve_manche() -> Callable[..., dict[str, Any]]:
    """Fabrique : démarre puis résout une manche au premier essai via le chemin de production."""
    from pere_noel_fremo.database import set_lutin_presence, start_score_defi
    from pere_noel_fremo.parcours import soumettre

    def _solve(
        db_path: Path,
        lutin_id: str,
        year: int,
        time_seconds: float,
        pseudo_lutin: str | None = None,
        manche_id: int = 1,
    ) -> dict[str, Any]:
        t0 = datetime(2026, 10, 14, 20, 0, 0, tzinfo=timezone.utc)
        manche: dict[str, Any] = {
            "id": manche_id,
            "categories": {"lutins": ["Barnabé", "Clémence"], "luges": ["Étoile Rouge", "Comète Bleue"]},
            "attributs": {"luge": "luges"},
            "solution": {"Barnabé": {"luge": "Comète Bleue"}, "Clémence": {"luge": "Étoile Rouge"}},
        }
        set_lutin_presence(db_path, lutin_id, year, True)
        start_score_defi(db_path, lutin_id, year, pseudo_lutin, manche_id=manche_id, now=t0)
        resultat = soumettre(db_path, lutin_id, year, manche, manche["solution"], t0 + timedelta(seconds=time_seconds))
        return {"statut": resultat.statut, "time_seconds": resultat.time_seconds, "attempts": resultat.attempts}

    return _solve
