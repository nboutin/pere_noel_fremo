from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def fake_gmail_service() -> Iterator[MagicMock]:
    """Empêche tout accès réel à Gmail/OAuth : le service est remplacé par un mock pour chaque test."""
    with patch("pere_noel_fremo.helper.build_gmail_service") as mock_build_service:
        yield mock_build_service


@pytest.fixture
def solve_manche() -> Callable[..., dict[str, Any]]:
    """Fabrique : démarre puis résout une manche au premier essai via le chemin de production."""
    from pere_noel_fremo.database import register_solve_attempt, start_score_defi

    def _solve(
        db_path: Path,
        lutin_id: str,
        year: int,
        time_seconds: float,
        pseudo_lutin: str | None = None,
        manche_id: int = 1,
    ) -> dict[str, Any]:
        t0 = datetime(2026, 10, 14, 20, 0, 0, tzinfo=timezone.utc)
        start_score_defi(db_path, lutin_id, year, pseudo_lutin, manche_id=manche_id, now=t0)
        return register_solve_attempt(
            db_path,
            lutin_id,
            year,
            manche_id,
            is_valid=True,
            now=t0 + timedelta(seconds=time_seconds),
        )

    return _solve
