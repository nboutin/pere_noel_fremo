from pathlib import Path
from typing import Any

import yaml
from pere_noel_fremo.campagne import ExpediteurMemoire
from pere_noel_fremo.cli import main
from pere_noel_fremo.database import (
    get_attributions,
    get_edition_status,
    init_db,
    set_edition_status,
    set_lutin_presence,
)


def test_complete_edition_cycle_e2e(tmp_path: Path, expediteur_memoire: ExpediteurMemoire) -> None:
    """Valide le cycle rituel complet du Père Noël de la Frémo :

    1. Initialisation de la base SQLite et import des données sources
    2. Campagne d'Annonce transmettant les Liens magiques (statut 'announced')
    3. Confirmations de présence des Lutins (présents et absents)
    4. Tirage au sort en mode Admin aveugle (statut 'drawn')
    5. Campagne de Révélation avec notification de la Carte à gratter (statut 'revealed')
    6. Export d'archive YAML de clôture (data_out.yml scellé avec historique)
    """
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"
    data_out_path = tmp_path / "data_out.yml"
    year = 2026

    # 4 Lutins : alice, bob, charlie, diane
    # Historique passé : alice -> bob, bob -> charlie
    # Exclusions : diane ne peut pas offrir à alice
    sample_data: dict[str, Any] = {
        "alice": {
            "fullname": "Alice A",
            "email": None,
            "exclude": [],
            "history": ["bob"],
        },
        "bob": {
            "fullname": "Bob B",
            "email": None,
            "exclude": [],
            "history": ["charlie"],
        },
        "charlie": {
            "fullname": "Charlie C",
            "email": None,
            "exclude": [],
            "history": [],
        },
        "diane": {
            "fullname": "Diane D",
            "email": None,
            "exclude": ["alice"],
            "history": [],
        },
    }

    sample_secure = {
        "sender_email": "pere.noel@fremo.org",
        "base_url": "https://noel.fremo.fr",
        "personnes": {
            "alice": {"email": "alice@fremo.org"},
            "bob": {"email": "bob@fremo.org"},
            "charlie": {"email": "charlie@fremo.org"},
            "diane": {"email": "diane@fremo.org"},
        },
    }

    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)

    # 1. Init-DB
    ret_init = main(
        [
            "init-db",
            "--db-path",
            str(db_path),
            "--data-in",
            str(data_in_path),
            "--secure-data",
            str(secure_data_path),
            "--year",
            str(year),
        ]
    )
    assert ret_init == 0

    # 2. Annonce (nominal)
    ret_annonce = main(
        [
            "annonce",
            "--db-path",
            str(db_path),
            "--secure-data",
            str(secure_data_path),
            "--year",
            str(year),
        ]
    )
    assert ret_annonce == 0
    assert len(expediteur_memoire.messages) == 4

    set_edition_status(db_path, year, "announced")
    assert get_edition_status(db_path, year) == "announced"

    # 3. Confirmations de présence
    # alice, bob et charlie confirment leur présence, diane est absente
    set_lutin_presence(db_path, "alice", year, True)
    set_lutin_presence(db_path, "bob", year, True)
    set_lutin_presence(db_path, "charlie", year, True)
    set_lutin_presence(db_path, "diane", year, False)

    # 4. Tirage au sort en mode Admin aveugle
    ret_tirage = main(
        [
            "tirage",
            "--db-path",
            str(db_path),
            "--year",
            str(year),
            "--organizer",
            "alice",
        ]
    )
    assert ret_tirage == 0
    assert get_edition_status(db_path, year) == "drawn"

    attributions = get_attributions(db_path, year)
    assert len(attributions) == 3
    assert "diane" not in attributions
    assert set(attributions.keys()) == {"alice", "bob", "charlie"}
    assert set(attributions.values()) == {"alice", "bob", "charlie"}

    # 5. Révélation (nominal)
    expediteur_memoire.messages.clear()
    ret_rev = main(
        [
            "revelation",
            "--db-path",
            str(db_path),
            "--secure-data",
            str(secure_data_path),
            "--year",
            str(year),
        ]
    )
    assert ret_rev == 0
    # Seuls les 3 lutins confirmés reçoivent l'email
    assert len(expediteur_memoire.messages) == 3
    rev_recipients = [m.destinataire for m in expediteur_memoire.messages]
    assert "diane@fremo.org" not in rev_recipients
    assert "alice@fremo.org" in rev_recipients
    assert "bob@fremo.org" in rev_recipients
    assert "charlie@fremo.org" in rev_recipients

    assert get_edition_status(db_path, year) == "revealed"

    # 6. Export d'archive YAML de clôture
    ret_export = main(
        [
            "export",
            "--db-path",
            str(db_path),
            "--year",
            str(year),
            "--output",
            str(data_out_path),
        ]
    )
    assert ret_export == 0
    assert data_out_path.exists()

    with open(data_out_path, encoding="utf-8") as f:
        exported_yaml = yaml.safe_load(f)

    # Clés racines ordonnées alphabétiquement
    assert list(exported_yaml.keys()) == ["alice", "bob", "charlie", "diane"]

    for lutin_id in ["alice", "bob", "charlie", "diane"]:
        entry = exported_yaml[lutin_id]
        assert entry["email"] is None
        assert isinstance(entry["exclude"], list)
        assert isinstance(entry["fullname"], str)
        assert isinstance(entry["history"], list)

    # Diane (absente) : son historique reste vide
    assert exported_yaml["diane"]["history"] == []
    assert exported_yaml["diane"]["exclude"] == ["alice"]

    # Alice, Bob, Charlie : leur historique se termine par leur bénéficiaire 2026
    assert exported_yaml["alice"]["history"][-1] == attributions["alice"]
    # Alice avait déjà 'bob' dans son historique passé
    assert exported_yaml["alice"]["history"][0] == "bob"

    assert exported_yaml["bob"]["history"][-1] == attributions["bob"]
    assert exported_yaml["charlie"]["history"][-1] == attributions["charlie"]
