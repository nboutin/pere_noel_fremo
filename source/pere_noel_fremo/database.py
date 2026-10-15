import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .migrations.m2026_10_backfill import compute_historical_attributions_map

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pseudos (
    year INTEGER NOT NULL,
    lutin_id TEXT NOT NULL,
    pseudo TEXT NOT NULL,
    PRIMARY KEY (year, lutin_id),
    UNIQUE (year, pseudo)
);

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
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'announced', 'drawn', 'revealed')),
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
    attempts INTEGER NOT NULL DEFAULT 0,
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


def parse_iso_or_legacy(val: str | datetime) -> datetime:
    """Parse une date soit au format ISO-8601 (avec millisecondes/fuseau), soit au format legacy SQLite."""
    if isinstance(val, datetime):
        dt = val
    else:
        raw = str(val).strip()
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def init_db(db_path: Path | str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db_connection(path)
    try:
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
                            attempts INTEGER NOT NULL DEFAULT 0,
                            PRIMARY KEY (lutin_id, year, manche_id)
                        );
                    """)
                    old_cols = [c[1] for c in conn.execute("PRAGMA table_info(_scores_defi_old);").fetchall()]
                    if "manche_id" in old_cols and "started_at" in old_cols:
                        conn.execute("""
                            INSERT INTO scores_defi (
                                lutin_id, year, manche_id, pseudo_lugeur,
                                started_at, solved, time_seconds, completed_at, attempts
                            )
                            SELECT
                                lutin_id, year, COALESCE(manche_id, 1), pseudo_lugeur, started_at,
                                solved, time_seconds, completed_at, CASE WHEN solved = 1 THEN 1 ELSE 0 END
                            FROM _scores_defi_old;
                        """)
                    elif "started_at" in old_cols:
                        conn.execute("""
                            INSERT INTO scores_defi (
                                lutin_id, year, manche_id, pseudo_lugeur,
                                started_at, solved, time_seconds, completed_at, attempts
                            )
                            SELECT
                                lutin_id, year, 1, pseudo_lugeur, started_at,
                                solved, time_seconds, completed_at, CASE WHEN solved = 1 THEN 1 ELSE 0 END
                            FROM _scores_defi_old;
                        """)
                    else:
                        conn.execute("""
                            INSERT INTO scores_defi (
                                lutin_id, year, manche_id, pseudo_lugeur,
                                started_at, solved, time_seconds, completed_at, attempts
                            )
                            SELECT
                                lutin_id, year, 1, pseudo_lugeur, COALESCE(completed_at, '2026-01-01 00:00:00'),
                                solved, time_seconds, completed_at, CASE WHEN solved = 1 THEN 1 ELSE 0 END
                            FROM _scores_defi_old;
                        """)
                    conn.execute("DROP TABLE _scores_defi_old;")

                # Migration idempotente de la colonne attempts si absente
                cols_after = [c[1] for c in conn.execute("PRAGMA table_info(scores_defi);").fetchall()]
                if "attempts" not in cols_after:
                    conn.execute("ALTER TABLE scores_defi ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;")
                    conn.execute("UPDATE scores_defi SET attempts = CASE WHEN solved = 1 THEN 1 ELSE 0 END;")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_defi_year_manche ON scores_defi(year, manche_id);")

            # Backfill started_at pour les anciens scores déjà résolus/complétés sans started_at
            conn.execute(
                """
                UPDATE scores_defi
                SET started_at = COALESCE(completed_at, '2026-01-01 00:00:00')
                WHERE started_at IS NULL AND (solved = 1 OR time_seconds IS NOT NULL OR completed_at IS NOT NULL);
                """
            )

            # Migration Ticket #33 : purger les lignes de scores_defi existantes où started_at IS NULL
            conn.execute("DELETE FROM scores_defi WHERE started_at IS NULL;")

            # Migration idempotente des pseudos pour scores_defi
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pseudos (
                    year INTEGER NOT NULL,
                    lutin_id TEXT NOT NULL,
                    pseudo TEXT NOT NULL,
                    PRIMARY KEY (year, lutin_id),
                    UNIQUE (year, pseudo)
                );
                """
            )
            scores_table_info = conn.execute("PRAGMA table_info(scores_defi);").fetchall()
            if scores_table_info:
                missing_scores_lutins = conn.execute(
                    """
                    SELECT DISTINCT s.year, s.lutin_id, s.pseudo_lugeur
                    FROM scores_defi s
                    WHERE NOT EXISTS (
                        SELECT 1 FROM pseudos p WHERE p.year = s.year AND p.lutin_id = s.lutin_id
                    )
                    ORDER BY s.year, s.lutin_id;
                    """
                ).fetchall()

                for r in missing_scores_lutins:
                    yr = int(r["year"])
                    lid = str(r["lutin_id"])
                    existing_pseudo = str(r["pseudo_lugeur"]) if r["pseudo_lugeur"] else None

                    assigned_p = None
                    if existing_pseudo:
                        already_taken = conn.execute(
                            "SELECT 1 FROM pseudos WHERE year = ? AND pseudo = ?;",
                            (yr, existing_pseudo),
                        ).fetchone()
                        if not already_taken:
                            try:
                                conn.execute(
                                    "INSERT INTO pseudos (year, lutin_id, pseudo) VALUES (?, ?, ?);",
                                    (yr, lid, existing_pseudo),
                                )
                                assigned_p = existing_pseudo
                            except sqlite3.IntegrityError:
                                assigned_p = None

                    if assigned_p is None:
                        assigned_p = get_or_assign_pseudo(conn, lid, yr)

                    conn.execute(
                        "UPDATE scores_defi SET pseudo_lugeur = ? WHERE year = ? AND lutin_id = ?;",
                        (assigned_p, yr, lid),
                    )

                conn.execute(
                    """
                    UPDATE scores_defi
                    SET pseudo_lugeur = (
                        SELECT p.pseudo FROM pseudos p
                        WHERE p.year = scores_defi.year AND p.lutin_id = scores_defi.lutin_id
                    )
                    WHERE EXISTS (
                        SELECT 1 FROM pseudos p
                        WHERE p.year = scores_defi.year AND p.lutin_id = scores_defi.lutin_id
                        AND p.pseudo != scores_defi.pseudo_lugeur
                    );
                    """
                )

            editions_info = conn.execute("PRAGMA table_info(editions);").fetchall()
            if editions_info:
                ed_cols = [c[1] for c in editions_info]
                if "date_repas" not in ed_cols:
                    conn.execute("ALTER TABLE editions ADD COLUMN date_repas TEXT;")
    finally:
        conn.close()


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

    init_db(db_path)
    conn = get_db_connection(db_path)
    personnes_secure = secure_data.get("personnes", {})

    try:
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
                hist_items = params.get("history") or []
                for order_idx, historical_id in enumerate(hist_items):
                    hist_year = (year - len(hist_items) + order_idx) if year is not None else None
                    if hist_year is not None:
                        conn.execute(
                            "INSERT OR IGNORE INTO editions (year, status) VALUES (?, 'drawn');",
                            (hist_year,),
                        )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO attributions (donneur_id, beneficiaire_id, year, order_index)
                        VALUES (?, ?, ?, ?);
                        """,
                        (lutin_id, historical_id, hist_year, order_idx),
                    )

            exclusion_count = conn.execute("SELECT COUNT(*) FROM exclusions;").fetchone()[0]
            attribution_count = conn.execute("SELECT COUNT(*) FROM attributions;").fetchone()[0]
    finally:
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


VALID_EDITION_STATUSES: tuple[str, ...] = ("draft", "announced", "drawn", "revealed")


def set_edition_status(db_path: Path | str, year: int, status: str) -> None:
    """Met à jour le statut d'une édition ('draft', 'announced', 'drawn', 'revealed')."""
    if status not in VALID_EDITION_STATUSES:
        raise ValueError(f"Statut d'édition invalide : {status!r}. Valeurs acceptées : {VALID_EDITION_STATUSES}")
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
                # Supprimer une attribution existante pour cette année et ce donneur si elle existe déjà
                conn.execute(
                    "DELETE FROM attributions WHERE donneur_id = ? AND year = ?;",
                    (donneur_id, year),
                )

                cur = conn.execute(
                    "SELECT COALESCE(MAX(order_index), -1) + 1 FROM attributions WHERE donneur_id = ?;",
                    (donneur_id,),
                )
                next_order_index = cur.fetchone()[0]

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


def get_past_attributions(db_path: Path | str, year: int) -> dict[str, list[str]]:
    """Récupère l'historique des attributions passées (strictement antérieures à l'année donnée, ADR-0008)."""
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT donneur_id, beneficiaire_id
            FROM attributions
            WHERE year < ?
            ORDER BY order_index ASC, id ASC;
            """,
            (year,),
        ).fetchall()
        past_map: dict[str, list[str]] = {}
        for row in rows:
            past_map.setdefault(row["donneur_id"], []).append(row["beneficiaire_id"])
        return past_map
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


def get_or_assign_pseudo(
    db_path: Path | str | sqlite3.Connection,
    lutin_id: str,
    year: int,
) -> str:
    """Vérifie si un pseudo est déjà persisté pour (year, lutin_id), sinon en tire un aléatoirement sans remise."""
    from .defi import ADJECTIFS_FESTIFS, ANIMAUX_LUGEURS

    conn: sqlite3.Connection
    close_after: bool
    if isinstance(db_path, sqlite3.Connection):
        conn = db_path
        close_after = False
    else:
        conn = get_db_connection(db_path)
        close_after = True

    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pseudos (
                    year INTEGER NOT NULL,
                    lutin_id TEXT NOT NULL,
                    pseudo TEXT NOT NULL,
                    PRIMARY KEY (year, lutin_id),
                    UNIQUE (year, pseudo)
                );
                """
            )
            for _ in range(10):
                row = conn.execute(
                    "SELECT pseudo FROM pseudos WHERE year = ? AND lutin_id = ?;",
                    (year, lutin_id),
                ).fetchone()
                if row is not None:
                    return str(row["pseudo"])

                assigned_rows = conn.execute(
                    "SELECT pseudo FROM pseudos WHERE year = ?;",
                    (year,),
                ).fetchall()
                assigned = {str(r["pseudo"]) for r in assigned_rows}

                all_combinations = [f"{animal} {adj}" for animal in ANIMAUX_LUGEURS for adj in ADJECTIFS_FESTIFS]
                available = [p for p in all_combinations if p not in assigned]
                if not available:
                    raise RuntimeError(
                        f"Espace de pseudos épuisé pour l'édition {year} "
                        f"({len(assigned)}/{len(all_combinations)} attribués)"
                    )

                chosen = secrets.choice(available)
                try:
                    conn.execute(
                        "INSERT INTO pseudos (year, lutin_id, pseudo) VALUES (?, ?, ?);",
                        (year, lutin_id, chosen),
                    )
                    return chosen
                except sqlite3.IntegrityError:
                    continue

            raise RuntimeError("Impossible d'attribuer un pseudo unique après plusieurs tentatives.")
    finally:
        if close_after:
            conn.close()


def get_lutin_pseudo(
    conn_or_path: Any,
    lutin_id: str,
    year: int,
) -> str | None:
    """Récupère le pseudo déjà persisté pour (year, lutin_id) s'il existe, sinon None (sans attribution)."""
    conn: sqlite3.Connection
    close_after: bool
    if isinstance(conn_or_path, sqlite3.Connection):
        conn = conn_or_path
        close_after = False
    else:
        conn = get_db_connection(conn_or_path)
        close_after = True

    try:
        row = conn.execute(
            "SELECT pseudo FROM pseudos WHERE year = ? AND lutin_id = ?;",
            (year, lutin_id),
        ).fetchone()
        if row is not None:
            return str(row["pseudo"])
        return None
    finally:
        if close_after:
            conn.close()


get_pseudo_for_lutin = get_lutin_pseudo


def _get_score_entry(conn: Any, lutin_id: str, year: int, manche_id: int = 1) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT lutin_id, year, manche_id, pseudo_lugeur, started_at, solved, time_seconds, completed_at, attempts
        FROM scores_defi
        WHERE lutin_id = ? AND year = ? AND manche_id = ?;
        """,
        (lutin_id, year, manche_id),
    ).fetchone()
    if not row:
        return {}
    res = dict(row)
    res["pseudo_lutin"] = res.get("pseudo_lugeur")
    return res


def get_score_defi(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    manche_id: int = 1,
) -> dict[str, Any]:
    """Récupère l'entrée score_defi pour un Lutin, une édition et une manche sans la créer si absente."""
    conn = get_db_connection(db_path)
    try:
        return _get_score_entry(conn, lutin_id, year, manche_id=manche_id)
    finally:
        conn.close()


def get_or_create_score_defi(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    pseudo_lugeur: str | None = None,
    manche_id: int = 1,
) -> dict[str, Any]:
    """Récupère ou initialise la ligne score_defi pour un Lutin, une édition et une manche."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            if pseudo_lugeur is None:
                pseudo = get_or_assign_pseudo(conn, lutin_id, year)
            else:
                pseudo = pseudo_lugeur
                row = conn.execute(
                    "SELECT pseudo FROM pseudos WHERE year = ? AND lutin_id = ?;",
                    (year, lutin_id),
                ).fetchone()
                if not row:
                    try:
                        conn.execute(
                            "INSERT INTO pseudos (year, lutin_id, pseudo) VALUES (?, ?, ?);",
                            (year, lutin_id, pseudo),
                        )
                    except sqlite3.IntegrityError:
                        pseudo = get_or_assign_pseudo(conn, lutin_id, year)
                else:
                    pseudo = str(row["pseudo"])

            conn.execute(
                """
                INSERT OR IGNORE INTO scores_defi (lutin_id, year, manche_id, pseudo_lugeur, solved)
                VALUES (?, ?, ?, ?, 0);
                """,
                (lutin_id, year, manche_id, pseudo),
            )
            return _get_score_entry(conn, lutin_id, year, manche_id=manche_id)
    finally:
        conn.close()


def start_score_defi(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    pseudo_lugeur: str | None = None,
    manche_id: int = 1,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Démarre le chronomètre du Défi du lutin pour une manche donnée si non déjà démarré ou résolu.

    Crée la ligne dans scores_defi si elle n'existe pas encore.
    """
    conn = get_db_connection(db_path)
    try:
        with conn:
            now_dt = parse_iso_or_legacy(now) if now is not None else datetime.now(timezone.utc)
            now_str = now_dt.isoformat()

            pseudo = get_or_assign_pseudo(conn, lutin_id, year) if pseudo_lugeur is None else pseudo_lugeur

            row = conn.execute(
                """
                SELECT started_at, solved, time_seconds
                FROM scores_defi
                WHERE lutin_id = ? AND year = ? AND manche_id = ?;
                """,
                (lutin_id, year, manche_id),
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO scores_defi (lutin_id, year, manche_id, pseudo_lugeur, started_at, solved)
                    VALUES (?, ?, ?, ?, ?, 0);
                    """,
                    (lutin_id, year, manche_id, pseudo, now_str),
                )
            elif not row["solved"] and row["started_at"] is None:
                conn.execute(
                    """
                    UPDATE scores_defi
                    SET started_at = ?
                    WHERE lutin_id = ? AND year = ? AND manche_id = ?;
                    """,
                    (now_str, lutin_id, year, manche_id),
                )
            return _get_score_entry(conn, lutin_id, year, manche_id=manche_id)
    finally:
        conn.close()


start_manche_defi = start_score_defi


def complete_score_defi(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    time_seconds: float,
    manche_id: int = 1,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Scelle la complétion du Défi du lutin pour une manche avec le temps officiel."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            now_dt = parse_iso_or_legacy(now) if now is not None else datetime.now(timezone.utc)
            now_str = now_dt.isoformat()

            row = conn.execute(
                """
                SELECT solved, attempts, started_at
                FROM scores_defi
                WHERE lutin_id = ? AND year = ? AND manche_id = ?;
                """,
                (lutin_id, year, manche_id),
            ).fetchone()
            # Si déjà résolu, on ne modifie pas le temps (essai unique officiel)
            if row and not row["solved"]:
                current_attempts = int(row["attempts"] or 0)
                new_attempts = max(1, current_attempts)
                started_at_val = row["started_at"] or now_str
                conn.execute(
                    """
                    UPDATE scores_defi
                    SET solved = 1,
                        attempts = ?,
                        time_seconds = ?,
                        completed_at = ?,
                        started_at = ?
                    WHERE lutin_id = ? AND year = ? AND manche_id = ?;
                    """,
                    (new_attempts, time_seconds, now_str, started_at_val, lutin_id, year, manche_id),
                )
            return _get_score_entry(conn, lutin_id, year, manche_id=manche_id)
    finally:
        conn.close()


def abandon_score_defi(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    manche_id: int = 1,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Scelle l'abandon d'une manche du Défi du lutin : chrono arrêté, tentative scellée."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            now_dt = parse_iso_or_legacy(now) if now is not None else datetime.now(timezone.utc)
            now_str = now_dt.isoformat()

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
                        completed_at = ?
                    WHERE lutin_id = ? AND year = ? AND manche_id = ?;
                    """,
                    (now_str, lutin_id, year, manche_id),
                )
            return _get_score_entry(conn, lutin_id, year, manche_id=manche_id)
    finally:
        conn.close()


def register_solve_attempt(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    manche_id: int,
    is_valid: bool,
    max_attempts: int = 3,
    penalty_seconds: float = 15.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Enregistre atomiquement une tentative de résolution, applique pénalités et scelle au plafond d'essais."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            row = conn.execute(
                """
                SELECT started_at, solved, completed_at, attempts
                FROM scores_defi
                WHERE lutin_id = ? AND year = ? AND manche_id = ?;
                """,
                (lutin_id, year, manche_id),
            ).fetchone()

            if not row:
                raise ValueError(f"Session introuvable pour {lutin_id} ({year}, manche {manche_id}).")

            if row["completed_at"] is not None or row["solved"]:
                return {
                    "already_completed": True,
                    "solved": bool(row["solved"]),
                    "attempts": int(row["attempts"] or 0),
                    "sealed": True,
                }

            if not row["started_at"]:
                raise ValueError("Le Défi du lutin doit être démarré avant d'être validé.")

            now_dt = parse_iso_or_legacy(now) if now is not None else datetime.now(timezone.utc)
            start_time = parse_iso_or_legacy(str(row["started_at"]))

            time_diff = (now_dt - start_time).total_seconds()
            current_attempts = int(row["attempts"] or 0)
            new_attempts = current_attempts + 1
            now_str = now_dt.isoformat()

            if is_valid:
                penalty = (new_attempts - 1) * penalty_seconds
                total_time = max(0.1, round(time_diff + penalty, 1))
                raw_time_seconds = max(0.1, round(time_diff, 1))
                conn.execute(
                    """
                    UPDATE scores_defi
                    SET solved = 1,
                        attempts = ?,
                        time_seconds = ?,
                        completed_at = ?
                    WHERE lutin_id = ? AND year = ? AND manche_id = ?;
                    """,
                    (new_attempts, total_time, now_str, lutin_id, year, manche_id),
                )
                return {
                    "already_completed": False,
                    "solved": True,
                    "sealed": True,
                    "attempts": new_attempts,
                    "essais_restants": max(0, max_attempts - new_attempts),
                    "raw_time_seconds": raw_time_seconds,
                    "penalty_seconds": penalty,
                    "time_seconds": total_time,
                    "completed_at": now_str,
                }
            else:
                if new_attempts >= max_attempts:
                    # 3e essai faux : manche scellée comme abandonnée
                    conn.execute(
                        """
                        UPDATE scores_defi
                        SET solved = 0,
                            attempts = ?,
                            time_seconds = NULL,
                            completed_at = ?
                        WHERE lutin_id = ? AND year = ? AND manche_id = ?;
                        """,
                        (new_attempts, now_str, lutin_id, year, manche_id),
                    )
                    return {
                        "already_completed": False,
                        "solved": False,
                        "sealed": True,
                        "attempts": new_attempts,
                        "essais_restants": 0,
                        "penalty_seconds": penalty_seconds,
                        "completed_at": now_str,
                    }
                else:
                    conn.execute(
                        """
                        UPDATE scores_defi
                        SET attempts = ?
                        WHERE lutin_id = ? AND year = ? AND manche_id = ?;
                        """,
                        (new_attempts, lutin_id, year, manche_id),
                    )
                    return {
                        "already_completed": False,
                        "solved": False,
                        "sealed": False,
                        "attempts": new_attempts,
                        "essais_restants": max_attempts - new_attempts,
                        "penalty_seconds": penalty_seconds,
                    }
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
        query = """
            SELECT lutin_id, pseudo_lugeur, manche_id, solved, time_seconds, completed_at, attempts, started_at
            FROM scores_defi
            WHERE year = ?
              AND (? IS NULL OR manche_id = ?)
              AND started_at IS NOT NULL
            ORDER BY
                CASE WHEN solved = 1 THEN 0 ELSE 1 END ASC,
                time_seconds ASC,
                completed_at ASC;
        """
        rows = conn.execute(query, (year, manche_id, manche_id)).fetchall()
        result: list[dict[str, Any]] = []
        for r in rows:
            entry = dict(r)
            entry["pseudo_lutin"] = entry.get("pseudo_lugeur")
            result.append(entry)
        return result
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


def backfill_historical_attributions(
    db_path: Path | str,
    res_dir: Path | str | None = None,
    purge_year: int | None = None,
) -> dict[str, int]:
    """Reconstitue et scelle l'historique des attributions millésimées (2014-2025).

    - Crée les éditions 2014..2025 avec le statut 'drawn'.
    - Si purge_year est spécifié (ex. 2026), purge les attributions de l'année et repasse l'édition en 'announced'.
    - Si purge_year est None (par défaut), ne purge aucune édition existante.
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

            if purge_year is not None:
                conn.execute("DELETE FROM attributions WHERE year = ?;", (purge_year,))
                conn.execute(
                    """
                    INSERT INTO editions (year, status) VALUES (?, 'announced')
                    ON CONFLICT(year) DO UPDATE SET status = 'announced';
                    """,
                    (purge_year,),
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
