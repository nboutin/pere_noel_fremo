import logging
from pathlib import Path
from typing import Any

import pytest
import yaml
from pere_noel_fremo.campagne import ExpediteurMemoire
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

    exp = ExpediteurMemoire()
    stats = send_revelations(db_path=db_path, secure_data_path=secure_data_path, year=2026, expediteur=exp)

    assert stats["total"] == 2  # Only confirmed lutins
    assert stats["sent"] == 2
    assert stats["echecs"] == 0
    assert len(exp.messages) == 2

    called_recipients = [m.destinataire for m in exp.messages]
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

    exp = ExpediteurMemoire()
    stats = send_revelations(
        db_path=db_path, secure_data_path=secure_data_path, year=2026, dry_run=True, expediteur=exp
    )

    assert stats["sent"] == 2
    assert exp.messages == []
    # In dry run, status must NOT transition
    assert get_edition_status(db_path, 2026) == "drawn"


def test_format_revelation_body_escapes_fullname_html() -> None:
    body = format_revelation_body("<p>{fullname}</p>", "Zoé <b>&</b>", "http://x/l", 2026)

    assert "Zoé &lt;b&gt;&amp;&lt;/b&gt;" in body
    assert "<b>" not in body


def test_send_revelations_failure_log_masks_address(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    db_path, secure_data_path = setup_sample_db(tmp_path)
    set_lutin_presence(db_path, "lutin_1", 2026, True)
    set_lutin_presence(db_path, "lutin_2", 2026, True)
    save_attributions(db_path, 2026, {"lutin_1": "lutin_2", "lutin_2": "lutin_1"})

    caplog.set_level(logging.INFO)
    send_revelations(
        db_path=db_path,
        secure_data_path=secure_data_path,
        year=2026,
        recipient_override="zed@exemple.fr",
        expediteur=ExpediteurMemoire(echouer_pour=["zed@exemple.fr"]),
    )

    assert caplog.records
    assert all("zed@exemple.fr" not in r.getMessage() for r in caplog.records)


def test_send_revelations_error_does_not_transition_status(tmp_path: Path) -> None:
    db_path, secure_data_path = setup_sample_db(tmp_path)

    set_lutin_presence(db_path, "lutin_1", 2026, True)
    set_lutin_presence(db_path, "lutin_2", 2026, True)
    save_attributions(db_path, 2026, {"lutin_1": "lutin_2", "lutin_2": "lutin_1"})

    exp = ExpediteurMemoire(echouer_pour=["lutin1@fremo.org", "lutin2@fremo.org"])
    stats = send_revelations(db_path=db_path, secure_data_path=secure_data_path, year=2026, expediteur=exp)

    assert stats["sent"] == 0
    assert stats["echecs"] == 2
    # On error, status must NOT transition
    assert get_edition_status(db_path, 2026) == "drawn"


def test_send_revelations_target_lutin_and_override_email(tmp_path: Path) -> None:
    db_path, secure_data_path = setup_sample_db(tmp_path)

    set_lutin_presence(db_path, "lutin_1", 2026, True)
    set_lutin_presence(db_path, "lutin_2", 2026, True)
    save_attributions(db_path, 2026, {"lutin_1": "lutin_2", "lutin_2": "lutin_1"})

    exp = ExpediteurMemoire()
    stats = send_revelations(
        db_path=db_path,
        secure_data_path=secure_data_path,
        year=2026,
        target_lutins=["lutin_1"],
        recipient_override="override@fremo.org",
        subject="Mon Sujet Révélation",
        expediteur=exp,
    )

    assert stats["sent"] == 1
    assert len(exp.messages) == 1
    assert exp.messages[0].destinataire == "override@fremo.org"
    assert exp.messages[0].objet == "Mon Sujet Révélation"

    # Targeted run with target_lutins must NOT transition edition status to 'revealed'
    assert get_edition_status(db_path, 2026) == "drawn"


def test_send_revelations_custom_template(tmp_path: Path) -> None:
    db_path, secure_data_path = setup_sample_db(tmp_path)
    custom_template = tmp_path / "custom_rev.html"
    custom_template.write_text("<h1>Special {fullname} - {year}</h1><a href='{magic_url}'>Click</a>", encoding="utf-8")

    set_lutin_presence(db_path, "lutin_1", 2026, True)
    save_attributions(db_path, 2026, {"lutin_1": "lutin_1"})

    exp = ExpediteurMemoire()
    stats = send_revelations(
        db_path=db_path,
        secure_data_path=secure_data_path,
        year=2026,
        template_path=custom_template,
        expediteur=exp,
    )

    assert stats["sent"] == 1
    assert "<h1>Special Lutin Un - 2026</h1>" in exp.messages[0].html
