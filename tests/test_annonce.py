from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml
from pere_noel_fremo.annonce import format_annonce_body, send_annonces
from pere_noel_fremo.database import get_db_connection, import_yaml_data, init_db


def test_format_annonce_body_injects_magic_url_and_fullname() -> None:
    template = "<p>Bonjour {fullname}, accédez à votre espace : <a href='{magic_url}'>Lien</a> pour l'année {year}</p>"
    formatted = format_annonce_body(
        template=template,
        fullname="Lutin Test",
        magic_url="https://noel.fremo.fr/lutin/tok123",
        year=2026,
    )
    assert "Lutin Test" in formatted
    assert "https://noel.fremo.fr/lutin/tok123" in formatted
    assert "2026" in formatted


def test_format_annonce_body_appends_magic_url_if_not_in_template() -> None:
    template = "<p>HoHoHo, Noël approche !</p>"
    formatted = format_annonce_body(
        template=template,
        fullname="Lutin Test",
        magic_url="https://noel.fremo.fr/lutin/tok123",
        year=2026,
    )
    assert "https://noel.fremo.fr/lutin/tok123" in formatted
    assert "Espace Lutin" in formatted


def test_send_annonces_creates_tokens_and_sends_emails(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"
    template_path = tmp_path / "annonce.txt"

    sample_data: dict[str, Any] = {
        "lutin_1": {"fullname": "Lutin Un", "email": None, "exclude": [], "history": []},
        "lutin_2": {"fullname": "Lutin Deux", "email": None, "exclude": [], "history": []},
        "lutin_skip": {"fullname": "Lutin Skip", "email": None, "exclude": [], "history": []},
    }
    sample_secure = {
        "sender_email": "pere.noel@fremo.org",
        "base_url": "https://noel.fremo.fr",
        "personnes": {
            "lutin_1": {"email": "lutin1@fremo.org"},
            "lutin_2": {"email": "lutin2@fremo.org"},
            "lutin_skip": {"email": "skip@fremo.org"},
        },
    }

    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)
    with open(template_path, "w", encoding="utf-8") as f:
        f.write("<p>Bonjour {fullname}, voici ton lien : {magic_url}</p>")

    import_yaml_data(db_path, data_in_path, secure_data_path)

    with patch("pere_noel_fremo.helper.gmail_send_email") as mock_send:
        stats = send_annonces(
            db_path=db_path,
            secure_data_path=secure_data_path,
            year=2026,
            template_path=template_path,
            absents=["lutin_skip"],
        )

        assert stats["total"] == 3
        assert stats["sent"] == 2
        assert stats["absents"] == 1
        assert mock_send.call_count == 2

        # Verify recipients and content
        called_recipients = [call.kwargs.get("toaddr") or call.args[3] for call in mock_send.call_args_list]
        assert "lutin1@fremo.org" in called_recipients
        assert "lutin2@fremo.org" in called_recipients
        assert "skip@fremo.org" not in called_recipients

        # Verify that sent_at timestamp was consigned in database
        from pere_noel_fremo.tokens import get_lutin_by_token

        conn = get_db_connection(db_path)
        token_row = conn.execute("SELECT token FROM tokens WHERE lutin_id = 'lutin_1';").fetchone()
        conn.close()
        assert token_row is not None
        lutin1_info = get_lutin_by_token(db_path, token_row["token"])
        assert lutin1_info is not None
        assert lutin1_info["sent_at"] is not None


def test_send_annonces_dry_run_does_not_send_emails(tmp_path: Path) -> None:
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
        stats = send_annonces(
            db_path=db_path,
            secure_data_path=secure_data_path,
            year=2026,
            dry_run=True,
        )
        assert stats["sent"] == 1
        mock_send.assert_not_called()


def test_send_annonces_with_port_in_base_url(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        "lutin_1": {"fullname": "Lutin Un", "email": None, "exclude": [], "history": []},
    }
    sample_secure = {
        "sender_email": "pere.noel@fremo.org",
        "base_url": "https://homelab.tail7d8b91.ts.net:10000",
        "personnes": {
            "lutin_1": {"email": "lutin1@fremo.org"},
        },
    }

    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)

    import_yaml_data(db_path, data_in_path, secure_data_path)

    with patch("pere_noel_fremo.helper.gmail_send_email") as mock_send:
        stats = send_annonces(
            db_path=db_path,
            secure_data_path=secure_data_path,
            year=2026,
        )
        assert stats["sent"] == 1
        call_body = mock_send.call_args.kwargs["body"]
        assert "https://homelab.tail7d8b91.ts.net:10000/lutin/" in call_body


def test_annonce_templates_contain_bulletproof_fallbacks() -> None:
    from pere_noel_fremo.annonce import DEFAULT_ANNONCE_TEMPLATE

    # Vérification du gabarit par défaut
    assert 'bgcolor="#991b1b"' in DEFAULT_ANNONCE_TEMPLATE
    assert "background-color: #991b1b" in DEFAULT_ANNONCE_TEMPLATE
    assert 'bgcolor="#dc2626"' in DEFAULT_ANNONCE_TEMPLATE
    assert "background-color: #dc2626" in DEFAULT_ANNONCE_TEMPLATE
    assert "color-scheme" in DEFAULT_ANNONCE_TEMPLATE
    assert (
        '<table role="presentation" border="0" cellspacing="0" cellpadding="0" align="center"'
        in DEFAULT_ANNONCE_TEMPLATE
    )

    # Vérification du gabarit res/2026/annonce.txt
    res_path = Path(__file__).resolve().parent.parent / "res" / "2026" / "annonce.txt"
    if res_path.exists():
        content = res_path.read_text(encoding="utf-8")
        assert 'bgcolor="#991b1b"' in content
        assert "background-color: #991b1b" in content
        assert 'bgcolor="#dc2626"' in content
        assert "background-color: #dc2626" in content
        assert '<table role="presentation" border="0" cellspacing="0" cellpadding="0" align="center"' in content


def test_send_annonces_handles_send_failure_leaves_sent_at_null_and_increments_echecs(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        "lutin_fail": {"fullname": "Lutin Fail", "email": None, "exclude": [], "history": []},
    }
    sample_secure = {
        "sender_email": "pere.noel@fremo.org",
        "personnes": {
            "lutin_fail": {"email": "fail@fremo.org"},
        },
    }
    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)

    import_yaml_data(db_path, data_in_path, secure_data_path)

    # Simulation d'un échec d'authentification ou d'envoi Gmail (load_credentials ou build qui lève)
    with patch("pere_noel_fremo.helper.build", side_effect=RuntimeError("Google API quota exceeded")):
        stats = send_annonces(
            db_path=db_path,
            secure_data_path=secure_data_path,
            year=2026,
        )

        assert stats["total"] == 1
        assert stats["sent"] == 0
        assert stats["absents"] == 0
        assert stats["sans_email"] == 0
        assert stats["echecs"] == 1

        # Vérification en base : sent_at doit impérativement rester NULL
        conn = get_db_connection(db_path)
        row = conn.execute("SELECT sent_at FROM tokens WHERE lutin_id = 'lutin_fail';").fetchone()
        conn.close()
        assert row is not None
        assert row["sent_at"] is None


def test_send_annonces_success_provides_text_body_with_magic_link(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        "lutin_ok": {"fullname": "Lutin Ok", "email": None, "exclude": [], "history": []},
    }
    sample_secure = {
        "sender_email": "pere.noel@fremo.org",
        "base_url": "https://noel.fremo.fr",
        "personnes": {
            "lutin_ok": {"email": "ok@fremo.org"},
        },
    }
    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)

    import_yaml_data(db_path, data_in_path, secure_data_path)

    with patch("pere_noel_fremo.helper.gmail_send_email") as mock_send:
        stats = send_annonces(
            db_path=db_path,
            secure_data_path=secure_data_path,
            year=2026,
        )

        assert stats["sent"] == 1
        assert stats["echecs"] == 0

        # Vérification en base : sent_at doit être renseigné
        conn = get_db_connection(db_path)
        row = conn.execute("SELECT sent_at FROM tokens WHERE lutin_id = 'lutin_ok';").fetchone()
        conn.close()
        assert row is not None
        assert row["sent_at"] is not None

        # Vérification de l'appel : text_body est fourni avec salutation et Lien magique
        assert mock_send.call_count == 1
        call_kwargs = mock_send.call_args.kwargs
        assert "text_body" in call_kwargs
        text_body = call_kwargs["text_body"]
        assert "Lutin Ok" in text_body
        assert "https://noel.fremo.fr/lutin/" in text_body
