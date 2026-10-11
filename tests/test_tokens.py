import sqlite3
from pathlib import Path

import pytest
from pere_noel_fremo.database import init_db
from pere_noel_fremo.tokens import (
    build_lien_magique_url,
    build_magic_url,
    create_or_get_token,
    generate_magic_token,
    get_lutin_by_token,
    mark_token_sent,
)


def test_generate_magic_token_is_secure_and_unique() -> None:
    token1 = generate_magic_token()
    token2 = generate_magic_token()
    assert isinstance(token1, str)
    assert len(token1) >= 16
    assert token1 != token2


def test_build_lien_magique_url_strips_trailing_slash() -> None:
    token = "xyz123"
    assert build_lien_magique_url("https://noel.fremo.fr", token) == "https://noel.fremo.fr/lutin/xyz123"
    assert build_lien_magique_url("https://noel.fremo.fr/", token) == "https://noel.fremo.fr/lutin/xyz123"
    # Alias compatibility
    assert build_magic_url("https://noel.fremo.fr", token) == "https://noel.fremo.fr/lutin/xyz123"


def test_create_or_get_token_is_idempotent_and_resolvable(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    conn = init_db(db_path)
    with conn:
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('lutin1', 'Lutin Un', 'lutin1@test.org');")
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
    conn.close()

    # First generation
    token1 = create_or_get_token(db_path, "lutin1", 2026)
    assert isinstance(token1, str)
    assert len(token1) >= 16

    # Idempotence: getting token again for same lutin and year returns same token
    token2 = create_or_get_token(db_path, "lutin1", 2026)
    assert token1 == token2

    # Resolving lutin by token
    resolved = get_lutin_by_token(db_path, token1)
    assert resolved is not None
    assert resolved["id"] == "lutin1"
    assert resolved["year"] == 2026
    assert resolved["fullname"] == "Lutin Un"
    assert resolved["email"] == "lutin1@test.org"
    assert resolved["sent_at"] is None

    # Marking token as sent
    mark_token_sent(db_path, token1)
    resolved_after_send = get_lutin_by_token(db_path, token1)
    assert resolved_after_send is not None
    assert resolved_after_send["sent_at"] is not None

    # Non-existent token returns None
    assert get_lutin_by_token(db_path, "unknown_token") is None


def test_token_table_enforces_unique_lutin_year(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    conn = init_db(db_path)
    with conn:
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('lutin1', 'Lutin Un', 'lutin1@test.org');")
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO tokens (token, lutin_id, year) VALUES ('tok_a', 'lutin1', 2026);")

    # Inserting duplicate token for same lutin and year must fail UNIQUE constraint
    with pytest.raises(sqlite3.IntegrityError), conn:
        conn.execute("INSERT INTO tokens (token, lutin_id, year) VALUES ('tok_b', 'lutin1', 2026);")

    conn.close()
