from pathlib import Path
from typing import Any

import pytest
import yaml
from pere_noel_fremo.cli import main
from pere_noel_fremo.database import get_lutins


def test_cli_init_db_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "test_fremo.db"
    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        "lutin_1": {
            "fullname": "Lutin Un",
            "email": None,
            "exclude": ["lutin_2"],
            "history": ["lutin_2"],
        },
        "lutin_2": {
            "fullname": "Lutin Deux",
            "email": None,
            "exclude": [],
            "history": [],
        },
    }
    sample_secure = {
        "personnes": {
            "lutin_1": {"email": "lutin1@test.org"},
            "lutin_2": {"email": "lutin2@test.org"},
        }
    }

    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)

    ret = main(
        [
            "init-db",
            "--db-path",
            str(db_path),
            "--data-in",
            str(data_in_path),
            "--secure-data",
            str(secure_data_path),
            "--year",
            "2026",
        ]
    )

    assert ret == 0
    captured = capsys.readouterr()
    assert "Importation réussie" in captured.out or "2 lutins" in captured.out

    lutins = get_lutins(db_path)
    assert len(lutins) == 2
    assert lutins["lutin_1"]["email"] == "lutin1@test.org"


def test_cli_init_db_missing_file_returns_error(tmp_path: Path) -> None:
    ret = main(
        [
            "init-db",
            "--db-path",
            str(tmp_path / "fremo.db"),
            "--data-in",
            str(tmp_path / "non_existent.yml"),
        ]
    )
    assert ret != 0


def test_cli_annonce_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from unittest.mock import patch

    from pere_noel_fremo.database import import_yaml_data, init_db

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        "lutin_1": {"fullname": "Lutin Un", "email": None, "exclude": [], "history": []},
    }
    sample_secure = {
        "sender_email": "pere.noel@fremo.org",
        "personnes": {"lutin_1": {"email": "lutin1@fremo.org"}},
    }
    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)

    import_yaml_data(db_path, data_in_path, secure_data_path)

    with patch("pere_noel_fremo.helper.gmail_send_email") as mock_send:
        ret = main(
            [
                "annonce",
                "--db-path",
                str(db_path),
                "--secure-data",
                str(secure_data_path),
                "--year",
                "2026",
            ]
        )
        assert ret == 0
        assert mock_send.call_count == 1
        captured = capsys.readouterr()
        assert "Annonce" in captured.out or "1 envoyée" in captured.out


def test_cli_annonce_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from unittest.mock import patch

    from pere_noel_fremo.database import import_yaml_data, init_db

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        "lutin_1": {"fullname": "Lutin Un", "email": None, "exclude": [], "history": []},
    }
    sample_secure = {
        "sender_email": "pere.noel@fremo.org",
        "personnes": {"lutin_1": {"email": "lutin1@fremo.org"}},
    }
    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)

    import_yaml_data(db_path, data_in_path, secure_data_path)

    with patch("pere_noel_fremo.helper.gmail_send_email") as mock_send:
        ret = main(
            [
                "annonce",
                "--db-path",
                str(db_path),
                "--secure-data",
                str(secure_data_path),
                "--year",
                "2026",
                "--dry-run",
            ]
        )
        assert ret == 0
        mock_send.assert_not_called()
        captured = capsys.readouterr()
        assert "Simulation" in captured.out or "dry-run" in captured.out or "1" in captured.out


def test_cli_annonce_with_absent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from unittest.mock import patch

    from pere_noel_fremo.database import import_yaml_data, init_db

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        "lutin_1": {"fullname": "Lutin Un", "email": None, "exclude": [], "history": []},
        "lutin_absent": {"fullname": "Lutin Absent", "email": None, "exclude": [], "history": []},
    }
    sample_secure = {
        "sender_email": "pere.noel@fremo.org",
        "personnes": {
            "lutin_1": {"email": "lutin1@fremo.org"},
            "lutin_absent": {"email": "absent@fremo.org"},
        },
    }
    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)

    import_yaml_data(db_path, data_in_path, secure_data_path)

    with patch("pere_noel_fremo.helper.gmail_send_email") as mock_send:
        ret = main(
            [
                "annonce",
                "--db-path",
                str(db_path),
                "--secure-data",
                str(secure_data_path),
                "--year",
                "2026",
                "--absent",
                "lutin_absent",
            ]
        )
        assert ret == 0
        assert mock_send.call_count == 1
        captured = capsys.readouterr()
        assert "1 absents" in captured.out
