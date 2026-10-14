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
    date_repas TEXT,
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
    manche_id INTEGER NOT NULL DEFAULT 1,
    pseudo_lugeur TEXT NOT NULL,
    started_at TIMESTAMP,
    solved BOOLEAN NOT NULL DEFAULT 0,
    time_seconds REAL,
    completed_at TIMESTAMP,
    PRIMARY KEY (lutin_id, year, manche_id)
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
        table_info = conn.execute("PRAGMA table_info(scores_defi);").fetchall()
        if table_info:
            cols = [c[1] for c in table_info]
            pk_cols = {c[1] for c in table_info if c[5] > 0}
            if "started_at" not in cols:
                conn.execute("ALTER TABLE scores_defi ADD COLUMN started_at TIMESTAMP;")
            if "manche_id" not in pk_cols:
                # Migration de l'ancienne table vers la clé composite (lutin_id, year, manche_id)
                conn.execute("ALTER TABLE scores_defi RENAME TO _scores_defi_old;")
                conn.execute("""
                    CREATE TABLE scores_defi (
                        lutin_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
                        year INTEGER NOT NULL REFERENCES editions(year) ON DELETE CASCADE,
                        manche_id INTEGER NOT NULL DEFAULT 1,
                        pseudo_lugeur TEXT NOT NULL,
                        started_at TIMESTAMP,
                        solved BOOLEAN NOT NULL DEFAULT 0,
                        time_seconds REAL,
                        completed_at TIMESTAMP,
                        PRIMARY KEY (lutin_id, year, manche_id)
                    );
                """)
                old_cols = [c[1] for c in conn.execute("PRAGMA table_info(_scores_defi_old);").fetchall()]
                if "manche_id" in old_cols and "started_at" in old_cols:
                    conn.execute("""
                        INSERT INTO scores_defi (
                            lutin_id, year, manche_id, pseudo_lugeur, started_at, solved, time_seconds, completed_at
                        )
                        SELECT
                            lutin_id, year, COALESCE(manche_id, 1), pseudo_lugeur, started_at,
                            solved, time_seconds, completed_at
                        FROM _scores_defi_old;
                    """)
                elif "started_at" in old_cols:
                    conn.execute("""
                        INSERT INTO scores_defi (
                            lutin_id, year, manche_id, pseudo_lugeur, started_at, solved, time_seconds, completed_at
                        )
                        SELECT
                            lutin_id, year, 1, pseudo_lugeur, started_at,
                            solved, time_seconds, completed_at
                        FROM _scores_defi_old;
                    """)
                else:
                    conn.execute("""
                        INSERT INTO scores_defi (
                            lutin_id, year, manche_id, pseudo_lugeur, started_at, solved, time_seconds, completed_at
                        )
                        SELECT
                            lutin_id, year, 1, pseudo_lugeur, NULL,
                            solved, time_seconds, completed_at
                        FROM _scores_defi_old;
                    """)
                conn.execute("DROP TABLE _scores_defi_old;")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_defi_year_manche ON scores_defi(year, manche_id);")

        editions_info = conn.execute("PRAGMA table_info(editions);").fetchall()
        if editions_info:
            ed_cols = [c[1] for c in editions_info]
            if "date_repas" not in ed_cols:
                conn.execute("ALTER TABLE editions ADD COLUMN date_repas TEXT;")
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

    edition_meta = data_in.pop("_edition", None)
    date_repas = None
    if isinstance(edition_meta, dict):
        date_repas = edition_meta.get("date_repas") or edition_meta.get("date_fete")

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
        # Création / mise à jour de l'édition si spécifiée
        if year is not None:
            if date_repas:
                conn.execute(
                    """
                    INSERT INTO editions (year, status, date_repas) VALUES (?, 'draft', ?)
                    ON CONFLICT(year) DO UPDATE SET date_repas = excluded.date_repas;
                    """,
                    (year, str(date_repas)),
                )
            else:
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


def get_edition_date_repas(db_path: Path | str, year: int) -> str | None:
    """Récupère la date ISO du Repas de Noël d'une édition ('YYYY-MM-DD')."""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            "SELECT date_repas FROM editions WHERE year = ?;",
            (year,),
        ).fetchone()
        if not row or not row["date_repas"]:
            return None
        return str(row["date_repas"])
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


def _get_score_entry(conn: Any, lutin_id: str, year: int, manche_id: int = 1) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT lutin_id, year, manche_id, pseudo_lugeur, started_at, solved, time_seconds, completed_at
        FROM scores_defi
        WHERE lutin_id = ? AND year = ? AND manche_id = ?;
        """,
        (lutin_id, year, manche_id),
    ).fetchone()
    return dict(row) if row else {}


def get_or_create_score_defi(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    pseudo_lugeur: str,
    manche_id: int = 1,
) -> dict[str, Any]:
    """Récupère ou initialise la ligne score_defi pour un Lutin, une édition et une manche."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO scores_defi (lutin_id, year, manche_id, pseudo_lugeur, solved)
                VALUES (?, ?, ?, ?, 0);
                """,
                (lutin_id, year, manche_id, pseudo_lugeur),
            )
            return _get_score_entry(conn, lutin_id, year, manche_id=manche_id)
    finally:
        conn.close()


def start_score_defi(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    manche_id: int = 1,
) -> dict[str, Any]:
    """Démarre le chronomètre du Défi du lutin pour une manche donnée si non déjà démarré ou résolu."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            row = conn.execute(
                """
                SELECT started_at, solved, time_seconds
                FROM scores_defi
                WHERE lutin_id = ? AND year = ? AND manche_id = ?;
                """,
                (lutin_id, year, manche_id),
            ).fetchone()
            if row and not row["solved"] and row["started_at"] is None:
                conn.execute(
                    """
                    UPDATE scores_defi
                    SET started_at = CURRENT_TIMESTAMP
                    WHERE lutin_id = ? AND year = ? AND manche_id = ?;
                    """,
                    (lutin_id, year, manche_id),
                )
            return _get_score_entry(conn, lutin_id, year, manche_id=manche_id)
    finally:
        conn.close()


def complete_score_defi(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    time_seconds: float,
    manche_id: int = 1,
) -> dict[str, Any]:
    """Scelle la complétion du Défi du lutin pour une manche avec le temps officiel."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            row = conn.execute(
                "SELECT solved FROM scores_defi WHERE lutin_id = ? AND year = ? AND manche_id = ?;",
                (lutin_id, year, manche_id),
            ).fetchone()
            # Si déjà résolu, on ne modifie pas le temps (essai unique officiel)
            if row and not row["solved"]:
                conn.execute(
                    """
                    UPDATE scores_defi
                    SET solved = 1,
                        time_seconds = ?,
                        completed_at = CURRENT_TIMESTAMP
                    WHERE lutin_id = ? AND year = ? AND manche_id = ?;
                    """,
                    (time_seconds, lutin_id, year, manche_id),
                )
            return _get_score_entry(conn, lutin_id, year, manche_id=manche_id)
    finally:
        conn.close()


def abandon_score_defi(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    manche_id: int = 1,
) -> dict[str, Any]:
    """Scelle l'abandon d'une manche du Défi du lutin : chrono arrêté, tentative scellée."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            row = conn.execute(
                "SELECT solved, completed_at FROM scores_defi WHERE lutin_id = ? AND year = ? AND manche_id = ?;",
                (lutin_id, year, manche_id),
            ).fetchone()
            if row and not row["solved"] and row["completed_at"] is None:
                conn.execute(
                    """
                    UPDATE scores_defi
                    SET solved = 0,
                        time_seconds = NULL,
                        completed_at = CURRENT_TIMESTAMP
                    WHERE lutin_id = ? AND year = ? AND manche_id = ?;
                    """,
                    (lutin_id, year, manche_id),
                )
            return _get_score_entry(conn, lutin_id, year, manche_id=manche_id)
    finally:
        conn.close()


def get_scores_classement(
    db_path: Path | str,
    year: int,
    manche_id: int | None = None,
) -> list[dict[str, Any]]:
    """Récupère le Tableau des scores ordonné pour une édition (filtré par manche si spécifié)."""
    conn = get_db_connection(db_path)
    try:
        if manche_id is not None:
            rows = conn.execute(
                """
                SELECT pseudo_lugeur, manche_id, solved, time_seconds, completed_at
                FROM scores_defi
                WHERE year = ? AND manche_id = ?
                ORDER BY
                    CASE WHEN solved = 1 THEN 0 ELSE 1 END ASC,
                    time_seconds ASC,
                    completed_at ASC;
                """,
                (year, manche_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT pseudo_lugeur, manche_id, solved, time_seconds, completed_at
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


def compute_historical_attributions_map(
    res_dir: Path | str,
) -> tuple[set[int], dict[str, list[tuple[str, int, int]]]]:
    """Reconstitue la cartographie exacte des attributions historiques millésimées (2014-2025).

    Retourne:
        - editions: L'ensemble des millésimes concernés (2014..2025).
        - user_attributions: Dictionnaire associant chaque donneur_id à la liste de ses
          attributions sous la forme (beneficiaire_id, year, order_index).
    """
    root = Path(res_dir)

    def _load_yaml(p: Path) -> Any:
        if not p.exists():
            return {}
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    d25_in = _load_yaml(root / "2025" / "data_in.yml")
    d25_out = _load_yaml(root / "2025" / "data_out.yml")
    d24_in = _load_yaml(root / "2024" / "data_in.yml")
    d24_out = _load_yaml(root / "2024" / "data_out.yml")
    d23_in = _load_yaml(root / "2023" / "2023_data_in.yml")
    d23_out = _load_yaml(root / "2023" / "2023_data_out.yml")
    d22_in = _load_yaml(root / "2022" / "data_in_2022.yml")
    d22_out = _load_yaml(root / "2022" / "data_out_2022.yml")
    d21_in = _load_yaml(root / "__bk" / "data_2021.yml")
    d21_out = _load_yaml(root / "__bk" / "data_export_2021.yml")
    data_19_raw = _load_yaml(root / "__bk" / "data.yml") or []
    d19_out = {item["id"]: item.get("history", []) for item in data_19_raw}
    data_18_raw = _load_yaml(root / "__bk" / "data_2018.yml") or []
    d18_in = {item["id"]: item.get("history", []) for item in data_18_raw}

    known_pairs: dict[tuple[str, str], int] = {}
    for u, d in d25_out.items():
        if len(d.get("history", [])) > len(d25_in.get(u, {}).get("history", [])):
            known_pairs[(u, d["history"][-1])] = 2025
    for u, d in d24_out.items():
        if len(d.get("history", [])) > len(d24_in.get(u, {}).get("history", [])):
            known_pairs[(u, d["history"][-1])] = 2024
    for u, d in d23_out.items():
        if len(d.get("history", [])) > len(d23_in.get(u, {}).get("history", [])):
            known_pairs[(u, d["history"][-1])] = 2023
    for u, d in d22_out.items():
        if len(d.get("history", [])) > len(d22_in.get(u, {}).get("history", [])):
            known_pairs[(u, d["history"][-1])] = 2022
    for u, d in d21_out.items():
        if len(d.get("history", [])) > len(d21_in.get(u, {}).get("history", [])):
            known_pairs[(u, d["history"][-1])] = 2021
    for u, h in d19_out.items():
        h_prev = d18_in.get(u, [])
        if len(h) > len(h_prev):
            known_pairs[(u, h[-1])] = 2019

    editions: set[int] = set()
    user_attributions: dict[str, list[tuple[str, int, int]]] = {}

    for u, udata in sorted(d25_out.items()):
        h = udata.get("history", [])
        user_entries: list[tuple[str, int, int]] = []
        user_years: list[int | None] = [None] * len(h)

        for idx, b in enumerate(h):
            if (u, b) in known_pairs:
                user_years[idx] = known_pairs[(u, b)]
            elif u == "jdenis" and b == "scarrea" and ("jdenis", "scarre") in known_pairs:
                user_years[idx] = known_pairs[("jdenis", "scarre")]

        for idx in range(len(h)):
            if user_years[idx] is None:
                if u == "cmouret" and idx == 3 and h[idx] == "aboinet":
                    user_years[idx] = 2018
                elif u in ("fleduff", "schouteau") and idx < 4:
                    user_years[idx] = 2015 + idx
                elif u == "tmoro" and idx == 0:
                    user_years[idx] = 2018
                elif u == "jdenis" and idx == 1:
                    user_years[idx] = 2015
                else:
                    init_len = len(d18_in.get(u, []))
                    user_years[idx] = 2017 - (init_len - 1 - idx)

        for idx, b in enumerate(h):
            norm_b = "scarre" if b == "scarrea" else b
            yr = user_years[idx]
            if yr is None:
                raise ValueError(f"Year is None for {u} -> {b} at index {idx}")
            editions.add(yr)
            user_entries.append((norm_b, yr, idx))

        user_attributions[u] = user_entries

    return editions, user_attributions


def backfill_historical_attributions(
    db_path: Path | str,
    res_dir: Path | str | None = None,
    purge_2026: bool = True,
) -> dict[str, int]:
    """Reconstitue et scelle l'historique des attributions millésimées (2014-2025).

    - Crée les éditions 2014..2025 avec le statut 'drawn'.
    - Si purge_2026 est True, purge les attributions 2026 et repasse l'édition 2026 en 'announced'.
    - Synchronise les attributions historiques avec leur millésime et leur index d'ordre.
    - Normalise la coquille historique 'scarrea' en 'scarre'.
    """
    if res_dir is None:
        p = Path(db_path)
        res_dir = p.parent if p.parent.name == "res" or (p.parent / "2025").exists() else Path("res")

    editions, user_attributions = compute_historical_attributions_map(res_dir)
    conn = get_db_connection(db_path)
    total_attributions = 0

    try:
        with conn:
            for yr in sorted(editions):
                conn.execute(
                    "INSERT INTO editions (year, status) VALUES (?, 'drawn') ON CONFLICT(year) DO NOTHING;",
                    (yr,),
                )

            if purge_2026:
                conn.execute("DELETE FROM attributions WHERE year = 2026;")
                conn.execute(
                    """
                    INSERT INTO editions (year, status) VALUES (2026, 'announced')
                    ON CONFLICT(year) DO UPDATE SET status = 'announced';
                    """
                )

            # Nettoyage des anciennes lignes sans millésime
            conn.execute("DELETE FROM attributions WHERE year IS NULL;")

            for donneur_id, items in user_attributions.items():
                conn.execute(
                    "INSERT OR IGNORE INTO lutins (id, fullname, email, is_active) VALUES (?, ?, NULL, 0);",
                    (donneur_id, donneur_id),
                )
                for beneficiaire_id, yr, order_idx in items:
                    conn.execute(
                        "INSERT OR IGNORE INTO lutins (id, fullname, email, is_active) VALUES (?, ?, NULL, 0);",
                        (beneficiaire_id, beneficiaire_id),
                    )
                    conn.execute(
                        """
                        INSERT INTO attributions (donneur_id, beneficiaire_id, year, order_index)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(donneur_id, beneficiaire_id, order_index) DO UPDATE SET
                            year = excluded.year;
                        """,
                        (donneur_id, beneficiaire_id, yr, order_idx),
                    )
                    total_attributions += 1

            # Nettoyage de l'identifiant fantôme 'scarrea'
            conn.execute("DELETE FROM attributions WHERE beneficiaire_id = 'scarrea' OR donneur_id = 'scarrea';")
            conn.execute("DELETE FROM exclusions WHERE lutin_id = 'scarrea' OR excluded_lutin_id = 'scarrea';")
            conn.execute("DELETE FROM lutins WHERE id = 'scarrea';")

        return {
            "editions": len(editions),
            "attributions": total_attributions,
        }
    finally:
        conn.close()
