import re
from pathlib import Path

import pere_noel_fremo


def test_version_matches_pyproject() -> None:
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    # tomllib n'existe pas en Python 3.10 (requires-python) : lecture par expression reguliere.
    match = re.search(r'^version = "([^"]+)"', pyproject_path.read_text(encoding="utf-8"), re.MULTILINE)
    assert match is not None
    pyproject_version = match.group(1)
    assert pere_noel_fremo.__version__ == "2.1.0"
    assert pyproject_version == "2.1.0"
    assert pere_noel_fremo.__version__ == pyproject_version


def test_changelog_mentions_version() -> None:
    changelog_path = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    content = changelog_path.read_text(encoding="utf-8")
    assert f"## [{pere_noel_fremo.__version__}]" in content
