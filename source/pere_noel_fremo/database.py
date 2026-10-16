import secrets
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from .edition import STATUTS_SQL, StatutEdition, sceller, statut

if TYPE_CHECKING:  # pragma: no cover
    from .admin import SyntheseEdition

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
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN (__STATUTS_EDITION__)),
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
    pseudo_lutin TEXT NOT NULL,
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


# Délai d'attente (secondes) d'un verrou d'écriture SQLite avant l'erreur "database is locked".
# Explicite pour ne pas dépendre du défaut de la bibliothèque : 5 s couvrent largement les
# transactions courtes de l'application tout en échouant vite en cas de blocage réel.
DB_TIMEOUT_SECONDS = 5.0


def begin_immediate(conn: sqlite3.Connection) -> None:
    """Ouvre une transaction d'écriture (verrou pris d'emblée) pour rendre un lire-puis-écrire indivisible."""
    conn.execute("BEGIN IMMEDIATE;")


@contextmanager
def _write_transaction(db: Path | str | sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Fournit une connexion en écriture : transaction propre au chemin, ou transaction de l'appelant si connexion."""
    if isinstance(db, sqlite3.Connection):
        yield db
        return
    conn = get_db_connection(db)
    try:
        with conn:
            begin_immediate(conn)
            yield conn
    finally:
        conn.close()


def get_db_connection(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=DB_TIMEOUT_SECONDS)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connection(conn_or_path: Path | str | sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Réutilise une connexion fournie, ou en ouvre une (fermée en sortie) à partir d'un chemin."""
    if isinstance(conn_or_path, sqlite3.Connection):
        yield conn_or_path
        return
    conn = get_db_connection(conn_or_path)
    try:
        yield conn
    finally:
        conn.close()


def parse_iso_or_legacy(val: str | datetime) -> datetime:
    """Parse une date soit au format ISO-8601 (avec millisecondes/fuseau), soit au format legacy SQLite."""
    if isinstance(val, datetime):
        dt = val
    else:
        raw = str(val).strip()
        # Python 3.10 ne comprend pas le suffixe Z dans fromisoformat.
        if raw.endswith(("Z", "z")):
            raw = raw[:-1] + "+00:00"
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
            conn.executescript(SCHEMA_SQL.replace("__STATUTS_EDITION__", STATUTS_SQL))
            table_info = conn.execute("PRAGMA table_info(scores_defi);").fetchall()
            if table_info:
                cols = [c[1] for c in table_info]
                if "pseudo_lugeur" in cols and "pseudo_lutin" not in cols:
                    # Migration (ticket #43) : ancien nom de colonne du schéma <= 2.0.0, renommé selon le glossaire.
                    conn.execute("ALTER TABLE scores_defi RENAME COLUMN pseudo_lugeur TO pseudo_lutin;")
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
                            pseudo_lutin TEXT NOT NULL,
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
                                lutin_id, year, manche_id, pseudo_lutin,
                                started_at, solved, time_seconds, completed_at, attempts
                            )
                            SELECT
                                lutin_id, year, COALESCE(manche_id, 1), pseudo_lutin, started_at,
                                solved, time_seconds, completed_at, CASE WHEN solved = 1 THEN 1 ELSE 0 END
                            FROM _scores_defi_old;
                        """)
                    elif "started_at" in old_cols:
                        conn.execute("""
                            INSERT INTO scores_defi (
                                lutin_id, year, manche_id, pseudo_lutin,
                                started_at, solved, time_seconds, completed_at, attempts
                            )
                            SELECT
                                lutin_id, year, 1, pseudo_lutin, started_at,
                                solved, time_seconds, completed_at, CASE WHEN solved = 1 THEN 1 ELSE 0 END
                            FROM _scores_defi_old;
                        """)
                    else:
                        conn.execute("""
                            INSERT INTO scores_defi (
                                lutin_id, year, manche_id, pseudo_lutin,
                                started_at, solved, time_seconds, completed_at, attempts
                            )
                            SELECT
                                lutin_id, year, 1, pseudo_lutin, COALESCE(completed_at, '2026-01-01 00:00:00'),
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
                    SELECT DISTINCT s.year, s.lutin_id, s.pseudo_lutin
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
                    existing_pseudo = str(r["pseudo_lutin"]) if r["pseudo_lutin"] else None

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
                        "UPDATE scores_defi SET pseudo_lutin = ? WHERE year = ? AND lutin_id = ?;",
                        (assigned_p, yr, lid),
                    )

                conn.execute(
                    """
                    UPDATE scores_defi
                    SET pseudo_lutin = (
                        SELECT p.pseudo FROM pseudos p
                        WHERE p.year = scores_defi.year AND p.lutin_id = scores_defi.lutin_id
                    )
                    WHERE EXISTS (
                        SELECT 1 FROM pseudos p
                        WHERE p.year = scores_defi.year AND p.lutin_id = scores_defi.lutin_id
                        AND p.pseudo != scores_defi.pseudo_lutin
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

            # Désactivation des lutins actifs retirés du fichier d'entrée (attributions et historique conservés)
            retires = [
                row[0] for row in conn.execute("SELECT id FROM lutins WHERE is_active = 1;") if row[0] not in data_in
            ]
            conn.executemany("UPDATE lutins SET is_active = 0 WHERE id = ?;", [(lutin_id,) for lutin_id in retires])
            desactives = len(retires)

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
        "desactives": desactives,
    }


def get_exclusions(conn_or_path: Path | str | sqlite3.Connection) -> dict[str, list[str]]:
    """Charge en une requête les exclusions de chaque Lutin ({lutin_id: [lutins exclus]})."""
    with connection(conn_or_path) as conn:
        rows = conn.execute("SELECT lutin_id, excluded_lutin_id FROM exclusions ORDER BY excluded_lutin_id;").fetchall()
    exclusions_map: dict[str, list[str]] = {}
    for row in rows:
        exclusions_map.setdefault(row["lutin_id"], []).append(row["excluded_lutin_id"])
    return exclusions_map


def _historique(conn: sqlite3.Connection, before_year: int | None) -> dict[str, list[str]]:
    """Bénéficiaires de chaque Donneur, sans doublon, triés par millésime (None = tous les millésimes)."""
    if before_year is None:
        rows = conn.execute(
            "SELECT donneur_id, beneficiaire_id FROM attributions ORDER BY year ASC, order_index ASC, id ASC;"
        ).fetchall()
    else:
        # Un millésime NULL (import hérité sans année, cf. ADR-0008) est du passé.
        rows = conn.execute(
            """
            SELECT donneur_id, beneficiaire_id
            FROM attributions
            WHERE year < ? OR year IS NULL
            ORDER BY year ASC, order_index ASC, id ASC;
            """,
            (before_year,),
        ).fetchall()
    history: dict[str, list[str]] = {}
    for row in rows:
        beneficiaires = history.setdefault(row["donneur_id"], [])
        if row["beneficiaire_id"] not in beneficiaires:
            beneficiaires.append(row["beneficiaire_id"])
    return history


def historique_avant(conn_or_path: Path | str | sqlite3.Connection, year: int) -> dict[str, list[str]]:
    """Historique d'un Donneur : ses Bénéficiaires des millésimes strictement antérieurs à `year` (ADR-0008).

    Chargé en une requête, sans doublon, trié par millésime. Source unique du tirage, de l'audit et de l'export.
    """
    with connection(conn_or_path) as conn:
        return _historique(conn, year)


def get_lutins(db_path: Path | str, active_only: bool = True) -> dict[str, dict[str, Any]]:
    """Récupère l'ensemble des lutins avec leurs exclusions et leur historique."""
    conn = get_db_connection(db_path)
    try:
        sql = "SELECT id, fullname, email FROM lutins"
        if active_only:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY id;"
        lutins_rows = conn.execute(sql).fetchall()

        exclusions_map = get_exclusions(conn)
        history_map = _historique(conn, None)

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


def get_lutin_presence(db_path: Path | str | sqlite3.Connection, lutin_id: str, year: int) -> bool | None:
    """Récupère l'état de confirmation de présence d'un Lutin pour une édition (None si non renseigné)."""
    conn = db_path if isinstance(db_path, sqlite3.Connection) else get_db_connection(db_path)
    try:
        row = conn.execute(
            "SELECT present FROM presences WHERE lutin_id = ? AND year = ?;",
            (lutin_id, year),
        ).fetchone()
        if row is None:
            return None
        return bool(row["present"])
    finally:
        if conn is not db_path:
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
    """Statut brut d'une édition, ou None si elle n'existe pas (lecture seule ; la logique vit dans `edition`)."""
    conn = get_db_connection(db_path)
    try:
        if conn.execute("SELECT 1 FROM editions WHERE year = ?;", (year,)).fetchone() is None:
            return None
        return statut(conn, year).value
    finally:
        conn.close()


def get_edition_date_repas(conn_or_path: Path | str | sqlite3.Connection, year: int) -> str | None:
    """Récupère la date ISO du Repas de Noël d'une édition ('YYYY-MM-DD') : lecteur unique de `editions.date_repas`."""
    with connection(conn_or_path) as conn:
        row = conn.execute(
            "SELECT date_repas FROM editions WHERE year = ?;",
            (year,),
        ).fetchone()
        if not row or not row["date_repas"]:
            return None
        return str(row["date_repas"])


VALID_EDITION_STATUSES: tuple[str, ...] = tuple(s.value for s in StatutEdition)


def set_edition_status(db_path: Path | str, year: int, status: str) -> None:
    """Écrit un statut d'édition sans contrôle de transition (réparation et fixtures ; le code applicatif
    passe par `edition.avancer`)."""
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


def _confirmed_rows(conn: sqlite3.Connection, year: int) -> list[sqlite3.Row]:
    """Lutins actifs ayant confirmé leur présence : requête unique de `get_confirmed_lutins` et `save_attributions`."""
    return conn.execute(
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


def get_confirmed_lutins(db_path: Path | str | sqlite3.Connection, year: int) -> dict[str, dict[str, Any]]:
    """Récupère les Lutins actifs ayant confirmé leur présence pour une édition donnée."""
    with connection(db_path) as conn:
        rows = _confirmed_rows(conn, year)

        exclusions_map = get_exclusions(conn)
        history_map = historique_avant(conn, year)

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


class PresencesChangees(Exception):
    """Levée quand les donneurs du tirage ne correspondent plus aux Lutins confirmés (rien n'est écrit)."""


def save_attributions(db_path: Path | str, year: int, attributions_map: dict[str, str]) -> None:
    """Enregistre de façon sécurisée et transactionnelle les attributions pour une édition."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            begin_immediate(conn)
            # Les donneurs doivent être exactement les Lutins confirmés au moment de l'écriture : une présence
            # modifiée depuis le calcul des paires invalide le tirage (rollback, Édition non scellée).
            confirmes = {row["id"] for row in _confirmed_rows(conn, year)}

            if confirmes != set(attributions_map):
                raise PresencesChangees("Les présences ont changé depuis le calcul du tirage.")

            # 0. Remplacer l'année entière (aucune ligne périmée) dans la même transaction
            conn.execute("DELETE FROM attributions WHERE year = ?;", (year,))

            # 1. Obtenir pour chaque donneur le prochain index d'ordre
            for donneur_id, beneficiaire_id in attributions_map.items():
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

            # 2. Sceller l'Édition dans la même transaction (TransitionEditionInterdite => rollback)
            sceller(conn, year)
    finally:
        conn.close()


def get_attributions(db_path: Path | str | sqlite3.Connection, year: int) -> dict[str, str]:
    """Récupère le dictionnaire des attributions {donneur_id: beneficiaire_id} pour une édition."""
    with connection(db_path) as conn:
        rows = conn.execute(
            "SELECT donneur_id, beneficiaire_id FROM attributions WHERE year = ? ORDER BY donneur_id;",
            (year,),
        ).fetchall()
    return {row["donneur_id"]: row["beneficiaire_id"] for row in rows}


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
    from .defi import ADJECTIFS_FESTIFS, ANIMAUX_LUTINS

    conn: sqlite3.Connection
    close_after: bool
    if isinstance(db_path, sqlite3.Connection):
        conn = db_path
        close_after = False
    else:
        conn = get_db_connection(db_path)
        close_after = True

    try:
        if close_after:
            with conn:
                begin_immediate(conn)
                return _assign_pseudo_in_transaction(conn, lutin_id, year, ADJECTIFS_FESTIFS, ANIMAUX_LUTINS)
        # Connexion fournie : on s'exécute dans la transaction de l'appelant, sans la valider.
        return _assign_pseudo_in_transaction(conn, lutin_id, year, ADJECTIFS_FESTIFS, ANIMAUX_LUTINS)
    finally:
        if close_after:
            conn.close()


def _assign_pseudo_in_transaction(
    conn: sqlite3.Connection,
    lutin_id: str,
    year: int,
    adjectifs: Sequence[str],
    animaux: Sequence[str],
) -> str:
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

        all_combinations = [f"{animal} {adj}" for animal in animaux for adj in adjectifs]
        available = [p for p in all_combinations if p not in assigned]
        if not available:
            raise RuntimeError(
                f"Espace de pseudos épuisé pour l'édition {year} ({len(assigned)}/{len(all_combinations)} attribués)"
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


def get_lutin_pseudo(
    conn_or_path: Path | str | sqlite3.Connection,
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


def _get_score_entry(conn: Any, lutin_id: str, year: int, manche_id: int = 1) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
        FROM scores_defi
        WHERE lutin_id = ? AND year = ? AND manche_id = ?;
        """,
        (lutin_id, year, manche_id),
    ).fetchone()
    if not row:
        return {}
    res = dict(row)
    return res


def get_score_defi(
    db_path: Path | str | sqlite3.Connection,
    lutin_id: str,
    year: int,
    manche_id: int = 1,
) -> dict[str, Any]:
    """Récupère l'entrée score_defi pour un Lutin, une édition et une manche sans la créer si absente."""
    conn = db_path if isinstance(db_path, sqlite3.Connection) else get_db_connection(db_path)
    try:
        return _get_score_entry(conn, lutin_id, year, manche_id=manche_id)
    finally:
        if conn is not db_path:
            conn.close()


def start_score_defi(
    db_path: Path | str | sqlite3.Connection,
    lutin_id: str,
    year: int,
    pseudo_lutin: str | None = None,
    manche_id: int = 1,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Démarre le chronomètre du Défi du lutin pour une manche donnée si non déjà démarré ou résolu.

    Crée la ligne dans scores_defi si elle n'existe pas encore.
    """
    with _write_transaction(db_path) as conn:
        now_dt = parse_iso_or_legacy(now) if now is not None else datetime.now(timezone.utc)
        now_str = now_dt.isoformat()

        pseudo = get_or_assign_pseudo(conn, lutin_id, year) if pseudo_lutin is None else pseudo_lutin

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
                INSERT INTO scores_defi (lutin_id, year, manche_id, pseudo_lutin, started_at, solved)
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


def abandon_score_defi(
    db_path: Path | str | sqlite3.Connection,
    lutin_id: str,
    year: int,
    manche_id: int = 1,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Scelle l'abandon d'une manche du Défi du lutin : chrono arrêté, tentative scellée."""
    with _write_transaction(db_path) as conn:
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


def get_scores_classement(
    db_path: Path | str,
    year: int,
    manche_id: int | None = None,
) -> list[dict[str, Any]]:
    """Récupère le Tableau des scores ordonné pour une édition (filtré par manche si spécifié)."""
    conn = get_db_connection(db_path)
    try:
        query = """
            SELECT lutin_id, pseudo_lutin, manche_id, solved, time_seconds, completed_at, attempts, started_at
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
            result.append(entry)
        return result
    finally:
        conn.close()


def get_admin_edition_summary(
    db_path: Path | str | sqlite3.Connection,
    year: int,
) -> "SyntheseEdition":
    """Agrège l'état d'avancement d'une Édition pour l'Espace Admin sous Admin aveugle."""
    from .admin import get_admin_edition_summary as _get_admin_edition_summary

    return _get_admin_edition_summary(db_path, year)
