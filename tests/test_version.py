from pathlib import Path

import pere_noel_fremo
import tomllib


def test_version_matches_pyproject() -> None:
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    pyproject_version = data["project"]["version"]
    assert pere_noel_fremo.__version__ == "2.0.1"
    assert pyproject_version == "2.0.1"
    assert pere_noel_fremo.__version__ == pyproject_version


def test_changelog_mentions_version() -> None:
    changelog_path = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    content = changelog_path.read_text(encoding="utf-8")
    assert f"## [{pere_noel_fremo.__version__}]" in content
