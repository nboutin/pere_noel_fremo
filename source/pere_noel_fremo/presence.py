"""Confirmation de présence d'un Lutin : garde d'Édition scellée et écriture dans une seule transaction.

La garde relit le statut de l'Édition sous le verrou d'écriture (`BEGIN IMMEDIATE`) : un scellement du Tirage au
sort ne peut donc pas s'intercaler entre la vérification et l'écriture.
"""

from enum import Enum
from pathlib import Path

from .database import begin_immediate, get_db_connection
from .edition import est_scellee, statut


class StatutPresence(Enum):
    """Issue d'une confirmation de présence."""

    ENREGISTREE = "enregistree"
    VERROUILLEE = "verrouillee"


def confirmer(db_path: Path | str, lutin_id: str, year: int, present: bool) -> StatutPresence:
    """Enregistre la présence d'un Lutin, sauf si l'Édition est scellée (`VERROUILLEE`, aucune écriture)."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            begin_immediate(conn)
            if est_scellee(statut(conn, year)):
                return StatutPresence.VERROUILLEE
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
            return StatutPresence.ENREGISTREE
    finally:
        conn.close()
