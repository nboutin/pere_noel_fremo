import os
import subprocess
import sys
from pathlib import Path

import pytest
from pere_noel_fremo.config import (
    PROJECT_ROOT,
    default_db_path,
    resolve_logs_dir,
    resolve_res_dir,
)


def test_resolve_res_dir_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_res = tmp_path / "custom_res"
    monkeypatch.setenv("FREMO_RES_DIR", str(custom_res))
    assert resolve_res_dir() == custom_res


def test_resolve_res_dir_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FREMO_RES_DIR", raising=False)
    # Ensure /app/res is treated as not existing
    orig_exists = Path.exists

    def mock_exists(self: Path) -> bool:
        if str(self) == str(Path("/app/res")):
            return False
        return orig_exists(self)

    monkeypatch.setattr(Path, "exists", mock_exists)
    assert resolve_res_dir() == PROJECT_ROOT / "res"


def test_resolve_res_dir_app_res(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FREMO_RES_DIR", raising=False)
    orig_exists = Path.exists

    def mock_exists(self: Path) -> bool:
        if str(self) == str(Path("/app/res")):
            return True
        return orig_exists(self)

    monkeypatch.setattr(Path, "exists", mock_exists)
    assert resolve_res_dir() == Path("/app/res")


def test_resolve_logs_dir_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_logs = tmp_path / "custom_logs"
    monkeypatch.setenv("FREMO_LOGS_DIR", str(custom_logs))
    assert resolve_logs_dir() == custom_logs


def test_resolve_logs_dir_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FREMO_LOGS_DIR", raising=False)
    orig_exists = Path.exists

    def mock_exists(self: Path) -> bool:
        if str(self) == str(Path("/app/logs")):
            return False
        return orig_exists(self)

    monkeypatch.setattr(Path, "exists", mock_exists)
    assert resolve_logs_dir() == PROJECT_ROOT / "logs"


def test_resolve_logs_dir_app_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FREMO_LOGS_DIR", raising=False)
    orig_exists = Path.exists

    def mock_exists(self: Path) -> bool:
        if str(self) == str(Path("/app/logs")):
            return True
        return orig_exists(self)

    monkeypatch.setattr(Path, "exists", mock_exists)
    assert resolve_logs_dir() == Path("/app/logs")


def test_default_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_res = tmp_path / "custom_res"
    monkeypatch.setenv("FREMO_RES_DIR", str(custom_res))
    assert default_db_path() == custom_res / "fremo.db"
    assert default_db_path(tmp_path) == tmp_path / "fremo.db"


def test_lazy_evaluation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FREMO_RES_DIR", raising=False)
    # First call with env unset
    res1 = resolve_res_dir()
    # Now set env dynamically
    custom = tmp_path / "dynamic_res"
    monkeypatch.setenv("FREMO_RES_DIR", str(custom))
    res2 = resolve_res_dir()
    assert res2 == custom
    assert res2 != res1


def test_import_web_no_side_effect(tmp_path: Path) -> None:
    """Importing pere_noel_fremo.web must not create fremo.db or any side effect."""
    custom_res = tmp_path / "empty_res"
    custom_res.mkdir(parents=True, exist_ok=True)
    db_file = custom_res / "fremo.db"

    env = os.environ.copy()
    env["FREMO_RES_DIR"] = str(custom_res)

    code = "import pere_noel_fremo.web; print('SUCCESS')"
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "SUCCESS" in result.stdout
    assert not db_file.exists(), "fremo.db should NOT be created on importing web module"


def test_fremo_res_dir_respected_by_defi_get_manche(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml
    from pere_noel_fremo import defi

    custom_res = tmp_path / "custom_res"
    manche_dir = custom_res / "2026" / "grilles"
    manche_dir.mkdir(parents=True, exist_ok=True)
    manche_file = manche_dir / "manche_1.yml"
    with open(manche_file, "w", encoding="utf-8") as f:
        yaml.safe_dump({"id": 1, "title": "Grille de Test Custom"}, f)

    monkeypatch.setenv("FREMO_RES_DIR", str(custom_res))
    manche = defi.get_manche(year=2026, manche_id=1)
    assert manche is not None
    assert manche["title"] == "Grille de Test Custom"


def test_fremo_res_dir_respected_by_cli_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pere_noel_fremo.cli import create_parser

    custom_res = tmp_path / "custom_res"
    monkeypatch.setenv("FREMO_RES_DIR", str(custom_res))

    parser = create_parser()
    args_init = parser.parse_args(["init-db"])
    assert args_init.db_path == custom_res / "fremo.db"
    assert args_init.secure_data == custom_res / "secure_data.yml"

    args_serve = parser.parse_args(["serve"])
    assert args_serve.db_path == custom_res / "fremo.db"

    args_tirage = parser.parse_args(["tirage"])
    assert args_tirage.db_path == custom_res / "fremo.db"


def test_fremo_res_dir_respected_by_helper_token_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pere_noel_fremo import helper

    custom_res = tmp_path / "custom_res"
    monkeypatch.setenv("FREMO_RES_DIR", str(custom_res))

    # Test via module attribute or helper function
    assert custom_res / "token.json" == helper.TOKEN_PATH
    if hasattr(helper, "get_token_path"):
        assert custom_res / "token.json" == helper.get_token_path()


def test_only_one_fremo_res_dir_occurrence_in_source() -> None:
    source_dir = PROJECT_ROOT / "source"
    occurrences = []
    for path in source_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line_num, line in enumerate(text.splitlines(), start=1):
            if "FREMO_RES_DIR" in line:
                occurrences.append((path.name, line_num, line.strip()))
    assert len(occurrences) == 1
    assert occurrences[0][0] == "config.py"


def test_get_admin_secrets_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pere_noel_fremo.config import get_admin_password, get_admin_session_secret

    monkeypatch.setenv("ADMIN_PASSWORD", "env_pass_123")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "env_secret_456")
    assert get_admin_password(tmp_path) == "env_pass_123"
    assert get_admin_session_secret(tmp_path) == "env_secret_456"


def test_get_admin_secrets_from_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml
    from pere_noel_fremo.config import get_admin_password, get_admin_session_secret

    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)

    secure_data = tmp_path / "secure_data.yml"
    with open(secure_data, "w", encoding="utf-8") as f:
        yaml.safe_dump({"admin_password": "yaml_pass_789", "admin_session_secret": "yaml_secret_abc"}, f)

    assert get_admin_password(tmp_path) == "yaml_pass_789"
    assert get_admin_session_secret(tmp_path) == "yaml_secret_abc"


def test_get_admin_secrets_fallback_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pere_noel_fremo.config import get_admin_password, get_admin_session_secret

    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)

    # Empty dir, no secure_data.yml
    assert get_admin_password(tmp_path) is None
    assert get_admin_session_secret(tmp_path) is None

    # Corrupted / invalid yaml
    secure_data = tmp_path / "secure_data.yml"
    secure_data.write_text(":: invalid yaml ::", encoding="utf-8")
    assert get_admin_password(tmp_path) is None
    assert get_admin_session_secret(tmp_path) is None
