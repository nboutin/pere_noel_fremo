from pathlib import Path
from typing import Any

import pytest
import yaml
from pere_noel_fremo.database import (
    import_yaml_data,
    init_db,
    save_attributions,
)
from pere_noel_fremo.export import (
    build_edition_export_data,
    export_edition_yaml,
)


def setup_export_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        "lutin_b": {
            "fullname": "Béatrice B",
            "email": None,
            "exclude": ["lutin_c"],
            "history": ["lutin_x", "lutin_y"],
        },
        "lutin_a": {
            "fullname": "Alain A",
            "email": None,
            "exclude": ["lutin_b"],
            "history": ["lutin_z"],
        },
        "lutin_c": {
            "fullname": "Claude C",
            "email": None,
            "exclude": [],
            "history": [],
        },
    }
    sample_secure = {
        "personnes": {
            "lutin_a": {"email": "a@fremo.org"},
            "lutin_b": {"email": "b@fremo.org"},
            "lutin_c": {"email": "c@fremo.org"},
        }
    }

    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)

    import_yaml_data(db_path, data_in_path, secure_data_path, year=2026)
    return db_path


def test_build_edition_export_data_structure(tmp_path: Path) -> None:
    db_path = setup_export_db(tmp_path)

    # Save attributions for 2026
    save_attributions(
        db_path,
        2026,
        {
            "lutin_a": "lutin_b",
            "lutin_b": "lutin_c",
            "lutin_c": "lutin_a",
        },
    )

    data = build_edition_export_data(db_path, 2026)

    # Root keys must be sorted alphabetically
    assert list(data.keys()) == ["lutin_a", "lutin_b", "lutin_c"]

    # Check lutin_a entry
    entry_a = data["lutin_a"]
    assert entry_a["email"] is None
    assert entry_a["fullname"] == "Alain A"
    assert entry_a["exclude"] == ["lutin_b"]
    # history had ["lutin_z"], now must end with current year beneficiaire ["lutin_b"]
    assert entry_a["history"] == ["lutin_z", "lutin_b"]

    # Check lutin_b entry
    entry_b = data["lutin_b"]
    assert entry_b["email"] is None
    assert entry_b["fullname"] == "Béatrice B"
    assert entry_b["exclude"] == ["lutin_c"]
    assert entry_b["history"] == ["lutin_x", "lutin_y", "lutin_c"]

    # Check lutin_c entry (empty initial history, now ends with "lutin_a")
    entry_c = data["lutin_c"]
    assert entry_c["email"] is None
    assert entry_c["fullname"] == "Claude C"
    assert entry_c["exclude"] == []
    assert entry_c["history"] == ["lutin_a"]


def test_export_edition_yaml_writes_file_and_protects_overwrite(tmp_path: Path) -> None:
    db_path = setup_export_db(tmp_path)
    save_attributions(db_path, 2026, {"lutin_a": "lutin_b", "lutin_b": "lutin_c", "lutin_c": "lutin_a"})

    output_file = tmp_path / "out" / "data_out.yml"

    # Nominal export
    exported_path = export_edition_yaml(db_path, 2026, output_file)
    assert exported_path == output_file
    assert output_file.exists()

    # Read back yaml and check structure
    with open(output_file, encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    assert list(loaded.keys()) == ["lutin_a", "lutin_b", "lutin_c"]
    assert loaded["lutin_a"]["history"] == ["lutin_z", "lutin_b"]

    # Re-exporting without overwrite flag must raise FileExistsError
    with pytest.raises(FileExistsError, match="existe déjà"):
        export_edition_yaml(db_path, 2026, output_file, overwrite=False)

    # Re-exporting with overwrite=True succeeds
    res = export_edition_yaml(db_path, 2026, output_file, overwrite=True)
    assert res == output_file


def test_export_absent_lutin_keeps_past_history_without_current_attribution(tmp_path: Path) -> None:
    db_path = setup_export_db(tmp_path)

    # Only lutin_a and lutin_b participate and have attributions in 2026, lutin_c was absent
    save_attributions(db_path, 2026, {"lutin_a": "lutin_b", "lutin_b": "lutin_a"})

    data = build_edition_export_data(db_path, 2026)

    # lutin_c should still be in export, but history remains empty / past
    assert "lutin_c" in data
    assert data["lutin_c"]["history"] == []
    assert data["lutin_a"]["history"] == ["lutin_z", "lutin_b"]
    assert data["lutin_b"]["history"] == ["lutin_x", "lutin_y", "lutin_a"]


def test_export_preserves_chronological_ordering_without_removing_prior_historical_entries(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data: dict[str, Any] = {
        "lutin_1": {
            "fullname": "Lutin 1",
            "email": None,
            "exclude": [],
            "history": ["lutin_2", "lutin_3"],
        },
        "lutin_2": {
            "fullname": "Lutin 2",
            "email": None,
            "exclude": [],
            "history": [],
        },
        "lutin_3": {
            "fullname": "Lutin 3",
            "email": None,
            "exclude": [],
            "history": [],
        },
    }
    sample_secure = {
        "personnes": {
            "lutin_1": {"email": "l1@fremo.org"},
            "lutin_2": {"email": "l2@fremo.org"},
            "lutin_3": {"email": "l3@fremo.org"},
        }
    }

    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)

    import_yaml_data(db_path, data_in_path, secure_data_path, year=2026)

    # Attribution 2026 : lutin_1 offre à nouveau à lutin_2
    save_attributions(db_path, 2026, {"lutin_1": "lutin_2"})

    data = build_edition_export_data(db_path, 2026)

    # L'entrée antérieure 'lutin_2' ne doit PAS avoir été supprimée de son rang initial
    assert data["lutin_1"]["history"] == ["lutin_2", "lutin_3"]
