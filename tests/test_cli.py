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


def test_cli_annonce_target_lutin_and_override_email(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from unittest.mock import patch

    from pere_noel_fremo.database import import_yaml_data, init_db

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        "lutin_1": {"fullname": "Lutin Un", "email": None, "exclude": [], "history": []},
        "lutin_2": {"fullname": "Lutin Deux", "email": None, "exclude": [], "history": []},
    }
    sample_secure = {
        "sender_email": "pere.noel@fremo.org",
        "personnes": {
            "lutin_1": {"email": "lutin1@fremo.org"},
            "lutin_2": {"email": "lutin2@fremo.org"},
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
                "--lutin",
                "lutin_1",
                "--override-email",
                "test-override@fremo.org",
            ]
        )
        assert ret == 0
        assert mock_send.call_count == 1
        assert mock_send.call_args.kwargs["toaddr"] == "test-override@fremo.org"


def test_cli_annonce_failure_exits_code_1_and_reports_echecs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from unittest.mock import patch

    from pere_noel_fremo.database import import_yaml_data, init_db
    from pere_noel_fremo.helper import EmailSendError

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

    with patch("pere_noel_fremo.helper.gmail_send_email", side_effect=EmailSendError("Failed to send")):
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
        assert ret == 1
        captured = capsys.readouterr()
        assert "1 échec" in captured.out or "1 échecs" in captured.out


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


def test_cli_serve_invokes_uvicorn(tmp_path: Path) -> None:
    from unittest.mock import patch

    db_path = tmp_path / "fremo.db"
    with patch("uvicorn.run") as mock_uvicorn:
        ret = main(
            [
                "serve",
                "--db-path",
                str(db_path),
                "--host",
                "0.0.0.0",
                "--port",
                "8080",
            ]
        )
        assert ret == 0
        assert mock_uvicorn.call_count == 1
        _, kwargs = mock_uvicorn.call_args
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 8080


def test_cli_tirage_admin_aveugle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from pere_noel_fremo.database import import_yaml_data, init_db, set_lutin_presence

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        f"l{i}": {"fullname": f"Lutin {i}", "email": None, "exclude": [], "history": []} for i in range(1, 5)
    }
    sample_secure = {"personnes": {f"l{i}": {"email": f"l{i}@test.org"} for i in range(1, 5)}}
    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)

    import_yaml_data(db_path, data_in_path, secure_data_path, year=2026)

    # Marquer la présence des 4 lutins
    for i in range(1, 5):
        set_lutin_presence(db_path, f"l{i}", 2026, present=True)

    ret = main(
        [
            "tirage",
            "--db-path",
            str(db_path),
            "--year",
            "2026",
            "--organizer",
            "l1",
        ]
    )
    assert ret == 0
    captured = capsys.readouterr()
    assert "*** SECRET ***" in captured.out
    assert "l1 ->" not in captured.out
    assert "-> l1" not in captured.out


def test_cli_audit_tirage_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from pere_noel_fremo.database import import_yaml_data, init_db, set_lutin_presence

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        f"l{i}": {"fullname": f"Lutin {i}", "email": None, "exclude": [], "history": []} for i in range(1, 5)
    }
    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump({"personnes": {}}, f)

    import_yaml_data(db_path, data_in_path, secure_data_path, year=2026)
    for i in range(1, 5):
        set_lutin_presence(db_path, f"l{i}", 2026, present=True)

    # Exécuter tirage
    assert main(["tirage", "--db-path", str(db_path), "--year", "2026"]) == 0
    capsys.readouterr()

    # Exécuter audit
    ret_audit = main(["audit-tirage", "--db-path", str(db_path), "--year", "2026"])
    assert ret_audit == 0
    captured_audit = capsys.readouterr()
    assert "VALIDE" in captured_audit.out or "valid" in captured_audit.out.lower()


def test_token_masking_filter_masks_tokens() -> None:
    import logging

    from pere_noel_fremo.web import TokenMaskingFilter

    masking_filter = TokenMaskingFilter()

    # Format direct en chaîne simple dans record.msg
    record1 = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="GET /lutin/aBcD_1234-xyz987654321 HTTP/1.1",
        args=(),
        exc_info=None,
    )
    assert masking_filter.filter(record1) is True
    assert record1.getMessage() == "GET /lutin/*** HTTP/1.1"

    # Format direct API avec sous-ressource
    record2 = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="POST /api/lutin/aBcD_1234-xyz987654321/presence HTTP/1.1",
        args=(),
        exc_info=None,
    )
    assert masking_filter.filter(record2) is True
    assert record2.getMessage() == "POST /api/lutin/***/presence HTTP/1.1"

    # Format uvicorn standard avec args tuple
    record3 = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:50000", "GET", "/lutin/aBcD_1234-xyz987654321", "1.1", 200),
        exc_info=None,
    )
    assert masking_filter.filter(record3) is True
    assert record3.getMessage() == '127.0.0.1:50000 - "GET /lutin/*** HTTP/1.1" 200'

    # Format uvicorn standard avec args tuple pour endpoint API
    record4 = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:50000", "POST", "/api/lutin/aBcD_1234-xyz987654321/presence", "1.1", 200),
        exc_info=None,
    )
    assert masking_filter.filter(record4) is True
    assert record4.getMessage() == '127.0.0.1:50000 - "POST /api/lutin/***/presence HTTP/1.1" 200'

    # Requête normale sans token : reste intacte
    record_public = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:50000", "GET", "/scores/2026", "1.1", 200),
        exc_info=None,
    )
    assert masking_filter.filter(record_public) is True
    assert record_public.getMessage() == '127.0.0.1:50000 - "GET /scores/2026 HTTP/1.1" 200'


def test_build_uvicorn_log_config() -> None:
    from pere_noel_fremo.cli import build_uvicorn_log_config
    from pere_noel_fremo.web import TokenMaskingFilter

    cfg = build_uvicorn_log_config()
    assert "token_masking" in cfg.get("filters", {})
    assert cfg["filters"]["token_masking"]["()"] is TokenMaskingFilter
    assert "token_masking" in cfg.get("loggers", {}).get("uvicorn.access", {}).get("filters", [])


def test_cli_serve_installs_token_masking_filter(tmp_path: Path) -> None:
    import logging
    from unittest.mock import patch

    from pere_noel_fremo.web import TokenMaskingFilter

    db_path = tmp_path / "fremo.db"
    access_logger = logging.getLogger("uvicorn.access")
    # Retirer les filtres existants pour le test
    initial_filters = list(access_logger.filters)
    access_logger.filters.clear()

    try:
        with patch("uvicorn.run") as mock_uvicorn:
            ret = main(
                [
                    "serve",
                    "--db-path",
                    str(db_path),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ]
            )
            assert ret == 0
            assert mock_uvicorn.call_count == 1
            call_kwargs = mock_uvicorn.call_args.kwargs
            assert "log_config" in call_kwargs
            log_cfg = call_kwargs["log_config"]
            assert "token_masking" in log_cfg.get("filters", {})
            assert "token_masking" in log_cfg.get("loggers", {}).get("uvicorn.access", {}).get("filters", [])
            has_masking_filter = any(isinstance(f, TokenMaskingFilter) for f in access_logger.filters)
            assert has_masking_filter is True
    finally:
        access_logger.filters = initial_filters
