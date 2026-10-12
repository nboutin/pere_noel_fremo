import sqlite3
from pathlib import Path
from typing import Any

import yaml

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lutins (
    id TEXT PRIMARY KEY,
    fullname TEXT NOT NULL,
    email TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exclusions (
    lutin_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
    excluded_lutin_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
    PRIMARY KEY (lutin_id, excluded_lutin_id)
);

CREATE TABLE IF NOT EXISTS editions (
    year INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tokens (
    token TEXT PRIMARY KEY,
    lutin_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
    year INTEGER NOT NULL REFERENCES editions(year) ON DELETE CASCADE,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (lutin_id, year)
);

CREATE TABLE IF NOT EXISTS presences (
    lutin_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
    year INTEGER NOT NULL REFERENCES editions(year) ON DELETE CASCADE,
    present BOOLEAN NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (lutin_id, year)
);

CREATE TABLE IF NOT EXISTS scores_defi (
    lutin_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
    year INTEGER NOT NULL REFERENCES editions(year) ON DELETE CASCADE,
    pseudo_lugeur TEXT NOT NULL,
    started_at TIMESTAMP,
    solved BOOLEAN NOT NULL DEFAULT 0,
    time_seconds REAL,
    completed_at TIMESTAMP,
    PRIMARY KEY (lutin_id, year)
);

CREATE TABLE IF NOT EXISTS attributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    donneur_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
    beneficiaire_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
    year INTEGER REFERENCES editions(year) ON DELETE CASCADE,
    order_index INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (donneur_id, beneficiaire_id, order_index)
);
"""


def get_db_connection(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db_connection(path)
    with conn:
        conn.executescript(SCHEMA_SQL)
    return conn


def import_yaml_data(
    db_path: Path | str,
    data_in_path: Path | str,
    secure_data_path: Path | str,
    year: int | None = None,
) -> dict[str, int]:
    """Import lutins, exclusions, et historique cumulé dans SQLite.

    Valide l'intégrité référentielle des données d'entrée et garantit l'idempotence
    sans suppression destructrice.
    """
    with open(data_in_path, encoding="utf-8") as stream:
        data_in = yaml.safe_load(stream) or {}

    secure_data: dict[str, Any] = {}
    if Path(secure_data_path).exists():
        with open(secure_data_path, encoding="utf-8") as stream:
            secure_data = yaml.safe_load(stream) or {}

    # Valider l'intégrité référentielle des exclusions
    all_lutin_ids = set(data_in.keys())
    for lutin_id, params in data_in.items():
        exclusions = params.get("exclude") or []
        for excluded_id in exclusions:
            if excluded_id not in all_lutin_ids:
                raise ValueError(f"Integrity error: lutin '{lutin_id}' excludes unknown lutin '{excluded_id}'")

    conn = init_db(db_path)
    personnes_secure = secure_data.get("personnes", {})

    with conn:
        # Création de l'édition si spécifiée
        if year is not None:
            conn.execute(
                "INSERT OR IGNORE INTO editions (year, status) VALUES (?, 'draft');",
                (year,),
            )

        # 1. Upsert des lutins actifs
        for lutin_id, params in data_in.items():
            fullname = params.get("fullname", lutin_id)
            email = personnes_secure.get(lutin_id, {}).get("email") or params.get("email")
            conn.execute(
                """
                INSERT INTO lutins (id, fullname, email, is_active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET
                    fullname = excluded.fullname,
                    email = excluded.email,
                    is_active = 1;
                """,
                (lutin_id, fullname, email),
            )

        # Enregistrement des participants historiques passés non actifs pour cette édition
        for _lutin_id, params in data_in.items():
            for historical_id in params.get("history") or []:
                conn.execute(
                    "INSERT OR IGNORE INTO lutins (id, fullname, email, is_active) VALUES (?, ?, NULL, 0);",
                    (historical_id, historical_id),
                )

        # 2. Synchronisation idempotente des exclusions
        for lutin_id, params in data_in.items():
            for excluded_id in params.get("exclude") or []:
                conn.execute(
                    "INSERT OR IGNORE INTO exclusions (lutin_id, excluded_lutin_id) VALUES (?, ?);",
                    (lutin_id, excluded_id),
                )

        # 3. Synchronisation idempotente de l'historique d'attributions
        for lutin_id, params in data_in.items():
            for order_idx, historical_id in enumerate(params.get("history") or []):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO attributions (donneur_id, beneficiaire_id, year, order_index)
                    VALUES (?, ?, NULL, ?);
                    """,
                    (lutin_id, historical_id, order_idx),
                )

        exclusion_count = conn.execute("SELECT COUNT(*) FROM exclusions;").fetchone()[0]
        attribution_count = conn.execute("SELECT COUNT(*) FROM attributions;").fetchone()[0]

    conn.close()
    return {
        "lutins": len(data_in),
        "exclusions": exclusion_count,
        "attributions": attribution_count,
    }


def _load_exclusions_and_history(
    conn: sqlite3.Connection,
    exclude_year: int | None = None,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Charge les correspondances d'exclusions et d'historique d'attributions."""
    exclusions_rows = conn.execute(
        "SELECT lutin_id, excluded_lutin_id FROM exclusions ORDER BY excluded_lutin_id;"
    ).fetchall()
    exclusions_map: dict[str, list[str]] = {}
    for row in exclusions_rows:
        exclusions_map.setdefault(row["lutin_id"], []).append(row["excluded_lutin_id"])

    if exclude_year is not None:
        history_rows = conn.execute(
            """
            SELECT donneur_id, beneficiaire_id
            FROM attributions
            WHERE year != ? OR year IS NULL
            ORDER BY order_index ASC, id ASC;
            """,
            (exclude_year,),
        ).fetchall()
    else:
        history_rows = conn.execute(
            "SELECT donneur_id, beneficiaire_id FROM attributions ORDER BY order_index ASC, id ASC;"
        ).fetchall()

    history_map: dict[str, list[str]] = {}
    for row in history_rows:
        history_map.setdefault(row["donneur_id"], []).append(row["beneficiaire_id"])

    return exclusions_map, history_map


def get_lutins(db_path: Path | str, active_only: bool = True) -> dict[str, dict[str, Any]]:
    """Récupère l'ensemble des lutins avec leurs exclusions et leur historique."""
    conn = get_db_connection(db_path)
    try:
        sql = "SELECT id, fullname, email FROM lutins"
        if active_only:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY id;"
        lutins_rows = conn.execute(sql).fetchall()

        exclusions_map, history_map = _load_exclusions_and_history(conn)

        result: dict[str, dict[str, Any]] = {}
        for row in lutins_rows:
            lutin_id = row["id"]
            result[lutin_id] = {
                "fullname": row["fullname"],
                "email": row["email"],
                "exclude": exclusions_map.get(lutin_id, []),
                "history": history_map.get(lutin_id, []),
            }
        return result
    finally:
        conn.close()


def get_lutin_history(db_path: Path | str, lutin_id: str) -> list[str]:
    """Récupère la liste ordonnée de l'historique des bénéficiaires pour un donneur."""
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT beneficiaire_id FROM attributions WHERE donneur_id = ? ORDER BY order_index ASC, id ASC;",
            (lutin_id,),
        ).fetchall()
        return [row["beneficiaire_id"] for row in rows]
    finally:
        conn.close()


def get_lutin_exclusions(db_path: Path | str, lutin_id: str) -> list[str]:
    """Récupère la liste des exclusions pour un lutin."""
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT excluded_lutin_id FROM exclusions WHERE lutin_id = ? ORDER BY excluded_lutin_id ASC;",
            (lutin_id,),
        ).fetchall()
        return [row["excluded_lutin_id"] for row in rows]
    finally:
        conn.close()


def get_lutin_presence(db_path: Path | str, lutin_id: str, year: int) -> bool | None:
    """Récupère l'état de confirmation de présence d'un Lutin pour une édition (None si non renseigné)."""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            "SELECT present FROM presences WHERE lutin_id = ? AND year = ?;",
            (lutin_id, year),
        ).fetchone()
        if row is None:
            return None
        return bool(row["present"])
    finally:
        conn.close()


def set_lutin_presence(db_path: Path | str, lutin_id: str, year: int, present: bool) -> None:
    """Enregistre ou met à jour la confirmation de présence d'un Lutin."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO presences (lutin_id, year, present, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(lutin_id, year) DO UPDATE SET
                    present = excluded.present,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (lutin_id, year, 1 if present else 0),
            )
    finally:
        conn.close()


def get_edition_status(db_path: Path | str, year: int) -> str | None:
    """Récupère le statut d'une édition ('draft', 'drawn', 'revealed')."""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            "SELECT status FROM editions WHERE year = ?;",
            (year,),
        ).fetchone()
        if not row:
            return None
        return str(row["status"])
    finally:
        conn.close()


def set_edition_status(db_path: Path | str, year: int, status: str) -> None:
    """Met à jour le statut d'une édition ('draft', 'drawn', 'revealed')."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO editions (year, status)
                VALUES (?, ?)
                ON CONFLICT(year) DO UPDATE SET status = excluded.status;
                """,
                (year, status),
            )
    finally:
        conn.close()


def get_confirmed_lutins(db_path: Path | str, year: int) -> dict[str, dict[str, Any]]:
    """Récupère les Lutins actifs ayant confirmé leur présence pour une édition donnée."""
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT l.id, l.fullname, l.email
            FROM lutins l
            JOIN presences p ON l.id = p.lutin_id
            WHERE l.is_active = 1
              AND p.year = ?
              AND p.present = 1
            ORDER BY l.id;
            """,
            (year,),
        ).fetchall()

        exclusions_map, history_map = _load_exclusions_and_history(conn, exclude_year=year)

        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            lutin_id = row["id"]
            result[lutin_id] = {
                "fullname": row["fullname"],
                "email": row["email"],
                "exclude": exclusions_map.get(lutin_id, []),
                "history": history_map.get(lutin_id, []),
            }
        return result
    finally:
        conn.close()


def save_attributions(db_path: Path | str, year: int, attributions_map: dict[str, str]) -> None:
    """Enregistre de façon sécurisée et transactionnelle les attributions pour une édition."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            # 1. Obtenir pour chaque donneur le prochain index d'ordre
            for donneur_id, beneficiaire_id in attributions_map.items():
                cur = conn.execute(
                    "SELECT COALESCE(MAX(order_index), -1) + 1 FROM attributions WHERE donneur_id = ?;",
                    (donneur_id,),
                )
                next_order_index = cur.fetchone()[0]

                # Supprimer une attribution existante pour cette année et ce donneur si elle existe déjà
                conn.execute(
                    "DELETE FROM attributions WHERE donneur_id = ? AND year = ?;",
                    (donneur_id, year),
                )

                conn.execute(
                    """
                    INSERT INTO attributions (donneur_id, beneficiaire_id, year, order_index)
                    VALUES (?, ?, ?, ?);
                    """,
                    (donneur_id, beneficiaire_id, year, next_order_index),
                )

            # 2. Marquer le statut de l'édition comme 'drawn'
            conn.execute(
                """
                INSERT INTO editions (year, status)
                VALUES (?, 'drawn')
                ON CONFLICT(year) DO UPDATE SET status = 'drawn';
                """,
                (year,),
            )
    finally:
        conn.close()


def get_attributions(db_path: Path | str, year: int) -> dict[str, str]:
    """Récupère le dictionnaire des attributions {donneur_id: beneficiaire_id} pour une édition."""
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT donneur_id, beneficiaire_id FROM attributions WHERE year = ? ORDER BY donneur_id;",
            (year,),
        ).fetchall()
        return {row["donneur_id"]: row["beneficiaire_id"] for row in rows}
    finally:
        conn.close()


def get_beneficiaire_for_lutin(
    db_path: Path | str,
    donneur_id: str,
    year: int,
) -> dict[str, str] | None:
    """Récupère l'identité du Bénéficiaire attribué à un Donneur pour une édition."""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT l.id, l.fullname, l.email
            FROM attributions a
            JOIN lutins l ON a.beneficiaire_id = l.id
            WHERE a.donneur_id = ? AND a.year = ?;
            """,
            (donneur_id, year),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "fullname": row["fullname"],
            "email": row["email"] or "",
        }
    finally:
        conn.close()


def _get_score_entry(conn: Any, lutin_id: str, year: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT lutin_id, year, pseudo_lugeur, started_at, solved, time_seconds, completed_at
        FROM scores_defi
        WHERE lutin_id = ? AND year = ?;
        """,
        (lutin_id, year),
    ).fetchone()
    return dict(row) if row else {}


def get_or_create_score_defi(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    pseudo_lugeur: str,
) -> dict[str, Any]:
    """Récupère ou initialise la ligne score_defi pour un Lutin et une édition."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO scores_defi (lutin_id, year, pseudo_lugeur, solved)
                VALUES (?, ?, ?, 0);
                """,
                (lutin_id, year, pseudo_lugeur),
            )
            return _get_score_entry(conn, lutin_id, year)
    finally:
        conn.close()


def start_score_defi(
    db_path: Path | str,
    lutin_id: str,
    year: int,
) -> dict[str, Any]:
    """Démarre le chronomètre du Défi de la luge si non déjà démarré ou résolu."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            row = conn.execute(
                "SELECT started_at, solved, time_seconds FROM scores_defi WHERE lutin_id = ? AND year = ?;",
                (lutin_id, year),
            ).fetchone()
            if row and not row["solved"] and row["started_at"] is None:
                conn.execute(
                    """
                    UPDATE scores_defi
                    SET started_at = CURRENT_TIMESTAMP
                    WHERE lutin_id = ? AND year = ?;
                    """,
                    (lutin_id, year),
                )
            return _get_score_entry(conn, lutin_id, year)
    finally:
        conn.close()


def complete_score_defi(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    time_seconds: float,
) -> dict[str, Any]:
    """Scelle la complétion du Défi de la luge avec le temps officiel."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            row = conn.execute(
                "SELECT solved FROM scores_defi WHERE lutin_id = ? AND year = ?;",
                (lutin_id, year),
            ).fetchone()
            # Si déjà résolu, on ne modifie pas le temps (essai unique officiel)
            if row and not row["solved"]:
                conn.execute(
                    """
                    UPDATE scores_defi
                    SET solved = 1,
                        time_seconds = ?,
                        completed_at = CURRENT_TIMESTAMP
                    WHERE lutin_id = ? AND year = ?;
                    """,
                    (time_seconds, lutin_id, year),
                )
            return _get_score_entry(conn, lutin_id, year)
    finally:
        conn.close()


def get_scores_classement(
    db_path: Path | str,
    year: int,
) -> list[dict[str, Any]]:
    """Récupère le Tableau des scores ordonné pour une édition."""
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT pseudo_lugeur, solved, time_seconds, completed_at
            FROM scores_defi
            WHERE year = ?
            ORDER BY
                CASE WHEN solved = 1 THEN 0 ELSE 1 END ASC,
                time_seconds ASC,
                completed_at ASC;
            """,
            (year,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_latest_edition_year(db_path: Path | str) -> int:
    """Récupère l'année de l'édition la plus récente (ou 2026 par défaut)."""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute("SELECT MAX(year) AS max_year FROM editions;").fetchone()
        if row and row["max_year"] is not None:
            return int(row["max_year"])
        return 2026
    finally:
        conn.close()
