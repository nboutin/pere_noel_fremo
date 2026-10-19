from pathlib import Path
from typing import Any

import pytest
import yaml
from pere_noel_fremo.campagne import ExpediteurMemoire
from pere_noel_fremo.cli import main
from pere_noel_fremo.database import import_yaml_data, init_db
from pere_noel_fremo.edition import StatutEdition, statut
from pere_noel_fremo.gabarits import DEFAULT_MANCHE_TEMPLATE
from pere_noel_fremo.manche_email import (
    charger_infos_manche,
    format_manche_body,
    format_manche_text,
    send_annonces_manche,
)


def test_charger_infos_manche_existing_yaml() -> None:
    infos = charger_infos_manche(2, 2026, res_dir="res")
    assert infos["id"] == 2
    assert infos["title"] == "Manche 2 : La Ronde des Étoiles"
    assert infos["estimated_time"] == "2 à 5 minutes"


def test_charger_infos_manche_missing_fallback(tmp_path: Path) -> None:
    infos = charger_infos_manche(99, 2026, res_dir=tmp_path)
    assert infos["id"] == 99
    assert infos["title"] == "Manche 99"
    assert infos["estimated_time"] == "2 à 5 minutes"


def test_format_manche_body_bulletproof_rendering() -> None:
    formatted = format_manche_body(
        template=DEFAULT_MANCHE_TEMPLATE,
        fullname="Lutin Astral",
        magic_url="https://noel.fremo.fr/lutin/magic123",
        year=2026,
        manche_id=2,
        manche_title="Manche 2 : La Ronde des Étoiles",
        estimated_time="2 à 5 minutes",
    )
    assert "Lutin Astral" in formatted
    assert "https://noel.fremo.fr/lutin/magic123" in formatted
    assert "Manche 2 : La Ronde des Étoiles" in formatted
    assert "2 à 5 minutes" in formatted
    assert "Édition 2026" in formatted
    assert "Repas de Noël" in formatted

    # Contrôles Bulletproof (ADR-0010)
    assert '<meta name="color-scheme" content="light dark">' in formatted
    assert '<meta name="supported-color-schemes" content="light dark">' in formatted
    assert 'bgcolor="#1e3a8a"' in formatted
    assert 'bgcolor="#2563eb"' in formatted
    assert '<table role="presentation"' in formatted


def test_format_manche_text_content() -> None:
    texte = format_manche_text(
        fullname="Lutin Test",
        magic_url="https://noel.fremo.fr/lutin/magic123",
        year=2026,
        manche_id=2,
        manche_title="Manche 2 : La Ronde des Étoiles",
        estimated_time="2 à 5 minutes",
    )
    assert "HOHOHO Lutin Test" in texte
    assert "Manche 2 : La Ronde des Étoiles" in texte
    assert "Durée estimée : 2 à 5 minutes" in texte
    assert "https://noel.fremo.fr/lutin/magic123" in texte
    assert "Repas de Noël" in texte


def test_send_annonces_manche_nominal_does_not_advance_edition(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

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
        yaml.safe_dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(sample_secure, f)

    import_yaml_data(db_path, data_in_path, secure_data_path, 2026)
    assert statut(db_path, 2026) is StatutEdition.DRAFT

    expediteur = ExpediteurMemoire()

    stats = send_annonces_manche(
        db_path=db_path,
        secure_data_path=secure_data_path,
        manche_id=2,
        year=2026,
        absents=["lutin_skip"],
        expediteur=expediteur,
    )

    assert stats["total"] == 3
    assert stats["sent"] == 2
    assert stats["absent"] == 1
    assert stats["failed"] == 0
    assert len(expediteur.messages) == 2

    # L'édition reste en DRAFT : l'annonce de manche ne fait pas avancer le cycle de vie
    assert statut(db_path, 2026) is StatutEdition.DRAFT

    # Vérification du sujet et du contenu du message
    premier_msg = expediteur.messages[0]
    assert "Défi du lutin : Manche 2" in premier_msg.objet
    assert "https://noel.fremo.fr/lutin/" in premier_msg.html


def test_send_annonces_manche_dry_run_and_override(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        "lutin_1": {"fullname": "Lutin Un", "email": "l1@fremo.org", "exclude": [], "history": []},
    }
    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({}, f)

    import_yaml_data(db_path, data_in_path, secure_data_path, 2026)

    # 1. Dry run
    expediteur_dry = ExpediteurMemoire()
    stats_dry = send_annonces_manche(
        db_path=db_path,
        secure_data_path=secure_data_path,
        manche_id=2,
        year=2026,
        dry_run=True,
        expediteur=expediteur_dry,
    )
    assert stats_dry["sent"] == 1
    assert len(expediteur_dry.messages) == 0

    # 2. Override email
    expediteur_override = ExpediteurMemoire()
    stats_override = send_annonces_manche(
        db_path=db_path,
        secure_data_path=secure_data_path,
        manche_id=2,
        year=2026,
        recipient_override="test@override.org",
        expediteur=expediteur_override,
    )
    assert stats_override["sent"] == 1
    assert len(expediteur_override.messages) == 1
    assert expediteur_override.messages[0].destinataire == "test@override.org"


def test_send_annonces_manche_targeted_lutin(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        "lutin_1": {"fullname": "Lutin Un", "email": "l1@fremo.org", "exclude": [], "history": []},
        "lutin_2": {"fullname": "Lutin Deux", "email": "l2@fremo.org", "exclude": [], "history": []},
    }
    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({}, f)

    import_yaml_data(db_path, data_in_path, secure_data_path, 2026)

    expediteur = ExpediteurMemoire()
    stats = send_annonces_manche(
        db_path=db_path,
        secure_data_path=secure_data_path,
        manche_id=2,
        year=2026,
        target_lutins=["lutin_1"],
        expediteur=expediteur,
    )
    assert stats["sent"] == 1
    assert len(expediteur.messages) == 1
    assert expediteur.messages[0].destinataire == "l1@fremo.org"


def test_cli_annonce_manche_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        "lutin_1": {"fullname": "Lutin Un", "email": "l1@fremo.org", "exclude": [], "history": []},
    }
    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({}, f)

    import_yaml_data(db_path, data_in_path, secure_data_path, 2026)

    ret = main(
        [
            "annonce-manche",
            "--manche",
            "2",
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
    captured = capsys.readouterr()
    assert "Simulation Annonce Manche 2" in captured.out
    assert "1 courriels préparés" in captured.out
