from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from pere_noel_fremo import helper
from pere_noel_fremo.database import (
    get_edition_status,
    import_yaml_data,
    init_db,
    save_attributions,
    set_edition_status,
    set_lutin_presence,
)
from pere_noel_fremo.revelation import (
    format_revelation_body,
    format_revelation_text,
    send_revelations,
)


def test_format_revelation_body_injects_placeholders() -> None:
    template = "<p>Bonjour {fullname}, révèle ton bénéficiaire : <a href='{lien_magique}'>Lien</a> pour {year}</p>"
    formatted = format_revelation_body(
        template=template,
        fullname="Lutin Test",
        lien_magique="https://noel.fremo.fr/lutin/tok123",
        year=2026,
    )
    assert "Lutin Test" in formatted
    assert "https://noel.fremo.fr/lutin/tok123" in formatted
    assert "2026" in formatted


def test_format_revelation_body_appends_magic_url_if_missing() -> None:
    template = "<p>HoHoHo, le tirage au sort est scellé !</p>"
    formatted = format_revelation_body(
        template=template,
        fullname="Lutin Test",
        lien_magique="https://noel.fremo.fr/lutin/tok123",
        year=2026,
    )
    assert "https://noel.fremo.fr/lutin/tok123" in formatted
    assert "Espace Lutin" in formatted


def test_format_revelation_text_contains_lien_magique_and_carte_a_gratter() -> None:
    text = format_revelation_text(
        fullname="Lutin Test",
        lien_magique="https://noel.fremo.fr/lutin/tok123",
        year=2026,
    )
    assert "HOHOHO Lutin Test" in text
    assert "2026" in text
    assert "https://noel.fremo.fr/lutin/tok123" in text
    assert "Carte à gratter" in text
    assert "Bénéficiaire" in text


def setup_sample_db(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        "lutin_1": {"fullname": "Lutin Un", "email": None, "exclude": [], "history": []},
        "lutin_2": {"fullname": "Lutin Deux", "email": None, "exclude": [], "history": []},
        "lutin_3": {"fullname": "Lutin Trois", "email": None, "exclude": [], "history": []},
    }
    sample_secure = {
        "sender_email": "pere.noel@fremo.org",
        "base_url": "https://noel.fremo.fr",
        "personnes": {
            "lutin_1": {"email": "lutin1@fremo.org"},
            "lutin_2": {"email": "lutin2@fremo.org"},
            "lutin_3": {"email": "lutin3@fremo.org"},
        },
    }

    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)

    import_yaml_data(db_path, data_in_path, secure_data_path, year=2026)
    return db_path, secure_data_path


def test_send_revelations_refuses_if_edition_not_drawn_or_revealed(tmp_path: Path) -> None:
    db_path, secure_data_path = setup_sample_db(tmp_path)

    # Status is draft by default
    set_edition_status(db_path, 2026, "draft")
    with pytest.raises(ValueError, match="draft"):
        send_revelations(db_path=db_path, secure_data_path=secure_data_path, year=2026)

    # Status announced is also refused
    set_edition_status(db_path, 2026, "announced")
    with pytest.raises(ValueError, match="announced"):
        send_revelations(db_path=db_path, secure_data_path=secure_data_path, year=2026)


def test_send_revelations_targets_only_confirmed_lutins(tmp_path: Path) -> None:
    db_path, secure_data_path = setup_sample_db(tmp_path)

    # Confirm lutin_1 and lutin_2, lutin_3 is absent (present=0)
    set_lutin_presence(db_path, "lutin_1", 2026, True)
    set_lutin_presence(db_path, "lutin_2", 2026, True)
    set_lutin_presence(db_path, "lutin_3", 2026, False)

    # Save attributions (sets status to drawn)
    save_attributions(db_path, 2026, {"lutin_1": "lutin_2", "lutin_2": "lutin_1"})
    assert get_edition_status(db_path, 2026) == "drawn"

    with patch("pere_noel_fremo.helper.gmail_send_email") as mock_send:
        stats = send_revelations(
            db_path=db_path,
            secure_data_path=secure_data_path,
            year=2026,
        )

        assert stats["total"] == 2  # Only confirmed lutins
        assert stats["sent"] == 2
        assert stats["echecs"] == 0
        assert mock_send.call_count == 2

        called_recipients = [call.kwargs.get("toaddr") or call.args[3] for call in mock_send.call_args_list]
        assert "lutin1@fremo.org" in called_recipients
        assert "lutin2@fremo.org" in called_recipients
        assert "lutin3@fremo.org" not in called_recipients

        # Edition status must transition to 'revealed' on nominal send
        assert get_edition_status(db_path, 2026) == "revealed"


def test_send_revelations_dry_run_does_not_send_or_transition(tmp_path: Path) -> None:
    db_path, secure_data_path = setup_sample_db(tmp_path)

    set_lutin_presence(db_path, "lutin_1", 2026, True)
    set_lutin_presence(db_path, "lutin_2", 2026, True)
    save_attributions(db_path, 2026, {"lutin_1": "lutin_2", "lutin_2": "lutin_1"})

    with patch("pere_noel_fremo.helper.gmail_send_email") as mock_send:
        stats = send_revelations(
            db_path=db_path,
            secure_data_path=secure_data_path,
            year=2026,
            dry_run=True,
        )

        assert stats["sent"] == 2
        assert mock_send.call_count == 0
        # In dry run, status must NOT transition
        assert get_edition_status(db_path, 2026) == "drawn"


def test_send_revelations_error_does_not_transition_status(tmp_path: Path) -> None:
    db_path, secure_data_path = setup_sample_db(tmp_path)

    set_lutin_presence(db_path, "lutin_1", 2026, True)
    set_lutin_presence(db_path, "lutin_2", 2026, True)
    save_attributions(db_path, 2026, {"lutin_1": "lutin_2", "lutin_2": "lutin_1"})

    with patch("pere_noel_fremo.helper.gmail_send_email", side_effect=helper.EmailSendError("SMTP error")):
        stats = send_revelations(
            db_path=db_path,
            secure_data_path=secure_data_path,
            year=2026,
        )

        assert stats["sent"] == 0
        assert stats["echecs"] == 2
        # On error, status must NOT transition
        assert get_edition_status(db_path, 2026) == "drawn"


def test_send_revelations_target_lutin_and_override_email(tmp_path: Path) -> None:
    db_path, secure_data_path = setup_sample_db(tmp_path)

    set_lutin_presence(db_path, "lutin_1", 2026, True)
    set_lutin_presence(db_path, "lutin_2", 2026, True)
    save_attributions(db_path, 2026, {"lutin_1": "lutin_2", "lutin_2": "lutin_1"})

    with patch("pere_noel_fremo.helper.gmail_send_email") as mock_send:
        stats = send_revelations(
            db_path=db_path,
            secure_data_path=secure_data_path,
            year=2026,
            target_lutins=["lutin_1"],
            recipient_override="override@fremo.org",
            subject="Mon Sujet Révélation",
        )

        assert stats["sent"] == 1
        assert mock_send.call_count == 1
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["toaddr"] == "override@fremo.org"
        assert call_kwargs["subject"] == "Mon Sujet Révélation"

        # Targeted run with target_lutins must NOT transition edition status to 'revealed'
        assert get_edition_status(db_path, 2026) == "drawn"


def test_send_revelations_custom_template(tmp_path: Path) -> None:
    db_path, secure_data_path = setup_sample_db(tmp_path)
    custom_template = tmp_path / "custom_rev.html"
    custom_template.write_text("<h1>Special {fullname} - {year}</h1><a href='{magic_url}'>Click</a>", encoding="utf-8")

    set_lutin_presence(db_path, "lutin_1", 2026, True)
    save_attributions(db_path, 2026, {"lutin_1": "lutin_1"})

    with patch("pere_noel_fremo.helper.gmail_send_email") as mock_send:
        stats = send_revelations(
            db_path=db_path,
            secure_data_path=secure_data_path,
            year=2026,
            template_path=custom_template,
        )

        assert stats["sent"] == 1
        call_kwargs = mock_send.call_args.kwargs
        assert "<h1>Special Lutin Un - 2026</h1>" in call_kwargs["body"]
