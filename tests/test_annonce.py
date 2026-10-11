from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml
from pere_noel_fremo.annonce import format_annonce_body, send_annonces
from pere_noel_fremo.database import import_yaml_data, init_db


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

        conn = init_db(db_path)
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
