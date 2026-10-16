from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from pere_noel_fremo.campagne import ExpediteurMemoire
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


def test_cli_annonce_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], expediteur_memoire: ExpediteurMemoire
) -> None:

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
    assert len(expediteur_memoire.messages) == 1
    captured = capsys.readouterr()
    assert "Annonce" in captured.out or "1 envoyée" in captured.out


def test_cli_annonce_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], expediteur_memoire: ExpediteurMemoire
) -> None:

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
    assert expediteur_memoire.messages == []
    captured = capsys.readouterr()
    assert "Simulation" in captured.out or "dry-run" in captured.out or "1" in captured.out


def test_cli_annonce_target_lutin_and_override_email(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], expediteur_memoire: ExpediteurMemoire
) -> None:

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
    assert len(expediteur_memoire.messages) == 1
    assert expediteur_memoire.messages[-1].destinataire == "test-override@fremo.org"


def test_cli_annonce_failure_exits_code_1_and_reports_echecs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], expediteur_memoire: ExpediteurMemoire
) -> None:

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

    expediteur_memoire.echouer_pour = ["lutin1@fremo.org"]
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


def test_cli_annonce_with_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], expediteur_memoire: ExpediteurMemoire
) -> None:

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
    assert len(expediteur_memoire.messages) == 1
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


def _setup_drawn_cli_db(tmp_path: Path) -> Path:
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
    assert main(["tirage", "--db-path", str(db_path), "--year", "2026"]) == 0
    return db_path


def test_cli_tirage_on_drawn_edition_refused_then_forced(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = _setup_drawn_cli_db(tmp_path)
    capsys.readouterr()

    assert main(["tirage", "--db-path", str(db_path), "--year", "2026"]) == 1
    refused = capsys.readouterr()
    assert "--force-retirage" in refused.out

    assert main(["tirage", "--db-path", str(db_path), "--year", "2026", "--force-retirage"]) == 0
    forced = capsys.readouterr()
    assert "Cartes à gratter" in forced.out + forced.err
    assert "*** SECRET ***" in forced.out
    assert "->" not in forced.out


def test_cli_tirage_dry_run_allowed_on_drawn_edition(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = _setup_drawn_cli_db(tmp_path)
    capsys.readouterr()
    assert main(["tirage", "--db-path", str(db_path), "--year", "2026", "--dry-run"]) == 0


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


def test_cli_revelation_refuses_when_not_drawn(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from pere_noel_fremo.database import init_db, set_edition_status

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    set_edition_status(db_path, 2026, "announced")

    ret = main(
        [
            "revelation",
            "--db-path",
            str(db_path),
            "--year",
            "2026",
            "--dry-run",
        ]
    )
    assert ret != 0
    captured = capsys.readouterr()
    assert "Erreur d'intégrité" in captured.out or "statut" in captured.out


def test_cli_revelation_nominal_and_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], expediteur_memoire: ExpediteurMemoire
) -> None:

    from pere_noel_fremo.database import (
        get_edition_status,
        import_yaml_data,
        init_db,
        save_attributions,
        set_lutin_presence,
    )

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    data_in = tmp_path / "data_in.yml"
    sec_data = tmp_path / "secure_data.yml"

    sample: dict[str, Any] = {"lutin_1": {"fullname": "Lutin 1", "email": None, "exclude": [], "history": []}}
    sec: dict[str, Any] = {"personnes": {"lutin_1": {"email": "l1@fremo.org"}}}

    with open(data_in, "w", encoding="utf-8") as f:
        yaml.dump(sample, f)
    with open(sec_data, "w", encoding="utf-8") as f:
        yaml.dump(sec, f)

    import_yaml_data(db_path, data_in, sec_data, year=2026)
    set_lutin_presence(db_path, "lutin_1", 2026, True)
    save_attributions(db_path, 2026, {"lutin_1": "lutin_1"})
    assert get_edition_status(db_path, 2026) == "drawn"

    # Dry-run
    ret_dry = main(
        [
            "revelation",
            "--db-path",
            str(db_path),
            "--secure-data",
            str(sec_data),
            "--year",
            "2026",
            "--dry-run",
        ]
    )
    assert ret_dry == 0
    assert get_edition_status(db_path, 2026) == "drawn"

    # Nominal execution
    ret_nom = main(
        [
            "revelation",
            "--db-path",
            str(db_path),
            "--secure-data",
            str(sec_data),
            "--year",
            "2026",
        ]
    )
    assert ret_nom == 0
    assert len(expediteur_memoire.messages) == 1
    assert get_edition_status(db_path, 2026) == "revealed"


def test_cli_revelation_targeted_lutin_does_not_transition_status(
    tmp_path: Path, expediteur_memoire: ExpediteurMemoire
) -> None:

    from pere_noel_fremo.database import (
        get_edition_status,
        import_yaml_data,
        init_db,
        save_attributions,
        set_lutin_presence,
    )

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    data_in = tmp_path / "data_in.yml"
    sec_data = tmp_path / "secure_data.yml"

    sample: dict[str, Any] = {
        "lutin_1": {"fullname": "Lutin 1", "email": None, "exclude": [], "history": []},
        "lutin_2": {"fullname": "Lutin 2", "email": None, "exclude": [], "history": []},
    }
    sec: dict[str, Any] = {
        "personnes": {
            "lutin_1": {"email": "l1@fremo.org"},
            "lutin_2": {"email": "l2@fremo.org"},
        }
    }

    with open(data_in, "w", encoding="utf-8") as f:
        yaml.dump(sample, f)
    with open(sec_data, "w", encoding="utf-8") as f:
        yaml.dump(sec, f)

    import_yaml_data(db_path, data_in, sec_data, year=2026)
    set_lutin_presence(db_path, "lutin_1", 2026, True)
    set_lutin_presence(db_path, "lutin_2", 2026, True)
    save_attributions(db_path, 2026, {"lutin_1": "lutin_2", "lutin_2": "lutin_1"})
    assert get_edition_status(db_path, 2026) == "drawn"

    ret = main(
        [
            "revelation",
            "--db-path",
            str(db_path),
            "--secure-data",
            str(sec_data),
            "--year",
            "2026",
            "--lutin",
            "lutin_1",
        ]
    )
    assert ret == 0
    assert len(expediteur_memoire.messages) == 1
    assert expediteur_memoire.messages[-1].destinataire == "l1@fremo.org"
    # Targeted run must NOT change the edition status to 'revealed'
    assert get_edition_status(db_path, 2026) == "drawn"


def test_cli_export_nominal_and_overwrite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from pere_noel_fremo.database import (
        import_yaml_data,
        init_db,
        save_attributions,
        set_lutin_presence,
    )

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    data_in = tmp_path / "data_in.yml"
    sec_data = tmp_path / "secure_data.yml"
    out_file = tmp_path / "exports" / "data_out.yml"

    sample: dict[str, Any] = {"lutin_1": {"fullname": "Lutin 1", "email": None, "exclude": [], "history": []}}
    with open(data_in, "w", encoding="utf-8") as f:
        yaml.dump(sample, f)
    with open(sec_data, "w", encoding="utf-8") as f:
        yaml.dump({"personnes": {}}, f)

    import_yaml_data(db_path, data_in, sec_data, year=2026)
    set_lutin_presence(db_path, "lutin_1", 2026, True)
    save_attributions(db_path, 2026, {"lutin_1": "lutin_1"})

    # Export nominal
    ret = main(
        [
            "export",
            "--db-path",
            str(db_path),
            "--year",
            "2026",
            "--output",
            str(out_file),
        ]
    )
    assert ret == 0
    assert out_file.exists()

    # Re-exporting without --overwrite fails
    ret_fail = main(
        [
            "export",
            "--db-path",
            str(db_path),
            "--year",
            "2026",
            "--data-out",
            str(out_file),
        ]
    )
    assert ret_fail != 0
    captured = capsys.readouterr()
    assert "existe déjà" in captured.out or "Erreur" in captured.out

    # Re-exporting with --overwrite succeeds
    ret_over = main(
        [
            "export",
            "--db-path",
            str(db_path),
            "--year",
            "2026",
            "--output",
            str(out_file),
            "--overwrite",
        ]
    )
    assert ret_over == 0


def _seed_single_lutin_campaign(tmp_path: Path) -> tuple[Path, Path]:
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
    return db_path, secure_data_path


def test_cli_annonce_defaults_to_non_interactive_auth(tmp_path: Path) -> None:
    db_path, secure_data_path = _seed_single_lutin_campaign(tmp_path)
    stats = {"total": 1, "sent": 1, "absents": 0, "sans_email": 0, "echecs": 0}

    with patch("pere_noel_fremo.cli.send_annonces", return_value=stats) as mock_send:
        ret = main(["annonce", "--db-path", str(db_path), "--secure-data", str(secure_data_path)])

    assert ret == 0
    assert mock_send.call_args.kwargs["interactive_auth"] is False


def test_cli_annonce_interactive_auth_flag_enables_local_reauthentication(tmp_path: Path) -> None:
    db_path, secure_data_path = _seed_single_lutin_campaign(tmp_path)
    stats = {"total": 1, "sent": 1, "absents": 0, "sans_email": 0, "echecs": 0}

    with patch("pere_noel_fremo.cli.send_annonces", return_value=stats) as mock_send:
        ret = main(["annonce", "--db-path", str(db_path), "--secure-data", str(secure_data_path), "--interactive-auth"])

    assert ret == 0
    assert mock_send.call_args.kwargs["interactive_auth"] is True


def test_cli_annonce_invalid_token_exits_with_code_1(
    tmp_path: Path, expediteur_memoire: ExpediteurMemoire, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path, secure_data_path = _seed_single_lutin_campaign(tmp_path)
    expediteur_memoire.echouer_pour = ["lutin1@fremo.org"]

    ret = main(["annonce", "--db-path", str(db_path), "--secure-data", str(secure_data_path)])

    assert ret == 1
    assert "1 échecs" in capsys.readouterr().out


def test_cli_init_db_inconsistent_yaml_returns_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_in_path = tmp_path / "data_in.yml"
    data_in_path.write_text(
        yaml.dump({"l1": {"fullname": "L1", "email": None, "exclude": ["fantome"], "history": []}}),
        encoding="utf-8",
    )

    ret = main(
        [
            "init-db",
            "--db-path",
            str(tmp_path / "fremo.db"),
            "--data-in",
            str(data_in_path),
            "--secure-data",
            str(tmp_path / "secure_data.yml"),
        ]
    )

    assert ret == 1
    assert "fantome" in capsys.readouterr().out


def test_cli_init_db_missing_file_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ret = main(["init-db", "--db-path", str(tmp_path / "fremo.db"), "--data-in", str(tmp_path / "absent.yml")])

    assert ret == 1
    assert "introuvable" in capsys.readouterr().out


def test_cli_init_db_does_not_fall_back_to_2025(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    res_dir = tmp_path / "res"
    (res_dir / "2025").mkdir(parents=True)
    (res_dir / "2025" / "data_in.yml").write_text(
        yaml.dump({"l1": {"fullname": "L1", "email": None, "exclude": [], "history": []}}), encoding="utf-8"
    )
    monkeypatch.setenv("FREMO_RES_DIR", str(res_dir))
    db_path = tmp_path / "fremo.db"

    ret = main(["init-db", "--db-path", str(db_path), "--year", "2027"])

    assert ret == 1
    out = capsys.readouterr().out
    assert str(res_dir / "2027" / "data_in.yml") in out
    assert not db_path.exists()


def test_cli_init_db_reports_deactivated_lutins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    res_dir = tmp_path / "res"
    (res_dir / "2027").mkdir(parents=True)
    monkeypatch.setenv("FREMO_RES_DIR", str(res_dir))
    db_path = tmp_path / "fremo.db"
    data_in = res_dir / "2027" / "data_in.yml"
    two: dict[str, Any] = {k: {"fullname": k, "email": None, "exclude": [], "history": []} for k in ("a", "b")}
    data_in.write_text(yaml.dump(two), encoding="utf-8")
    assert main(["init-db", "--db-path", str(db_path), "--year", "2027"]) == 0
    data_in.write_text(yaml.dump({"a": two["a"]}), encoding="utf-8")
    capsys.readouterr()

    assert main(["init-db", "--db-path", str(db_path), "--year", "2027"]) == 0

    assert "1 lutins désactivés" in capsys.readouterr().out


def test_cli_annonce_send_annonces_raising_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path, secure_data_path = _seed_single_lutin_campaign(tmp_path)

    with patch("pere_noel_fremo.cli.send_annonces", side_effect=RuntimeError("boom")):
        ret = main(["annonce", "--db-path", str(db_path), "--secure-data", str(secure_data_path)])

    assert ret == 1
    assert "boom" in capsys.readouterr().out


def _annonce_template_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, years_with_template: tuple[str, ...]
) -> Path | None:
    res_dir = tmp_path / "res"
    res_dir.mkdir()
    for year in years_with_template:
        (res_dir / year).mkdir()
        (res_dir / year / "annonce.txt").write_text("gabarit", encoding="utf-8")
    monkeypatch.setenv("FREMO_RES_DIR", str(res_dir))
    stats = {"sent": 0, "absents": 0, "total": 0}
    with patch("pere_noel_fremo.cli.send_annonces", return_value=stats) as mock_send:
        ret = main(["annonce", "--db-path", str(tmp_path / "fremo.db"), "--year", "2026", "--dry-run"])
    assert ret == 0
    template: Path | None = mock_send.call_args.kwargs["template_path"]
    return template


def test_cli_annonce_defaults_to_year_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    template = _annonce_template_used(tmp_path, monkeypatch, ("2026", "2025"))
    assert template == tmp_path / "res" / "2026" / "annonce.txt"


def test_cli_annonce_does_not_fall_back_to_2025_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _annonce_template_used(tmp_path, monkeypatch, ("2025",)) is None
    assert "gabarit intégré" in capsys.readouterr().out


def test_cli_annonce_without_any_template_uses_builtin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _annonce_template_used(tmp_path, monkeypatch, ()) is None


def test_cli_tirage_failure_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from pere_noel_fremo.database import init_db

    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    ret = main(["tirage", "--db-path", str(db_path), "--year", "2026"])

    assert ret == 1
    assert "insuffisant" in capsys.readouterr().out


def test_cli_tirage_parses_cheater_pairs_and_ignores_malformed_ones(tmp_path: Path) -> None:
    db_path = _setup_drawn_cli_db(tmp_path)

    with patch("pere_noel_fremo.tirage.run_tirage") as mock_run:
        mock_run.return_value.success = True
        mock_run.return_value.get_masked_summary.return_value = "ok"
        ret = main(["tirage", "--db-path", str(db_path), "--cheater", "invalide", "--cheater", "l1: l2"])

    assert ret == 0
    assert mock_run.call_args.kwargs["cheaters"] == [{"donneur": "l1", "beneficiaire": "l2"}]


def test_cli_unknown_argument_returns_2_without_exception(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tirage", "--inconnu"]) == 2
    assert main(["commande-inconnue"]) == 2
    capsys.readouterr()


def test_cli_without_command_returns_non_zero_without_exception(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    capsys.readouterr()


def test_cli_tirage_invalid_audit_shows_categories_without_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    from pere_noel_fremo import tirage as tirage_module
    from pere_noel_fremo.audit import AuditResult
    from pere_noel_fremo.database import import_yaml_data, init_db, set_lutin_presence

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"
    ids = ["alice_x", "bob_y", "carl_z", "dora_w"]
    sample_data: dict[str, Any] = {i: {"fullname": i, "email": None, "exclude": [], "history": []} for i in ids}
    sample_secure = {"personnes": {i: {"email": f"{i}@test.org"} for i in ids}}
    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)
    import_yaml_data(db_path, data_in_path, secure_data_path, year=2026)
    for i in ids:
        set_lutin_presence(db_path, i, 2026, present=True)

    def fake_audit(*args: object, **kwargs: object) -> AuditResult:
        return AuditResult(
            is_valid=False,
            total_lutins=4,
            errors=["Violation d'exclusion : 'alice_x' s'est vu attribuer 'bob_y', qui est exclu."],
            error_categories=["Violation d'exclusion"],
        )

    with patch.object(tirage_module, "audit_pairs", fake_audit):
        ret = main(["tirage", "--db-path", str(db_path), "--year", "2026"])

    assert ret == 1
    out = capsys.readouterr().out + caplog.text
    assert "Violation d'exclusion" in out
    for lutin_id in ids:
        assert lutin_id not in out


def test_cli_annee_par_defaut_est_l_edition_la_plus_recente(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from pere_noel_fremo.database import init_db, set_edition_status

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    set_edition_status(db_path, 2031, "drawn")

    main(["audit-tirage", "--db-path", str(db_path)])

    assert "(2031)" in capsys.readouterr().out


@pytest.fixture
def journaux_isoles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    import logging

    monkeypatch.setenv("FREMO_LOGS_DIR", str(tmp_path / "logs"))
    root = logging.getLogger("")
    avant = list(root.handlers)
    yield tmp_path / "logs" / "pere_noel.log"
    for handler in list(root.handlers):
        if handler not in avant:
            handler.close()
            root.removeHandler(handler)


def _main_journalisant(message: str) -> int:
    import logging

    def faux_init(_args: Any) -> int:
        logging.getLogger("pere_noel_fremo.test").info(message)
        return 0

    with patch("pere_noel_fremo.cli.handle_init_db", faux_init):
        return main(["init-db"])


def test_main_ecrit_les_journaux_applicatifs(journaux_isoles: Path) -> None:
    assert _main_journalisant("message applicatif") == 0

    assert "message applicatif" in journaux_isoles.read_text(encoding="utf-8")


def test_main_masque_les_jetons_dans_le_fichier(journaux_isoles: Path) -> None:
    _main_journalisant("GET /lutin/secret123 ok")

    contenu = journaux_isoles.read_text(encoding="utf-8")
    assert "/lutin/***" in contenu
    assert "secret123" not in contenu


def test_main_deux_fois_sans_handler_en_double(journaux_isoles: Path) -> None:
    import logging

    _main_journalisant("un")
    nombre = len(logging.getLogger("").handlers)
    _main_journalisant("deux")

    assert len(logging.getLogger("").handlers) == nombre
    assert journaux_isoles.read_text(encoding="utf-8").count("deux") == 1
