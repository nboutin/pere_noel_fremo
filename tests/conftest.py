from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def fake_gmail_service() -> Iterator[MagicMock]:
    """Empêche tout accès réel à Gmail/OAuth : le service est remplacé par un mock pour chaque test."""
    with patch("pere_noel_fremo.helper.build_gmail_service") as mock_build_service:
        yield mock_build_service
