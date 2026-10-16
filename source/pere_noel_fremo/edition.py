"""Cycle de vie d'une Édition : unique propriétaire du statut et du prédicat de scellement.

Cycle : ``draft`` -> ``announced`` -> ``drawn`` -> ``revealed``.

- L'Annonce fait passer ``draft`` à ``announced`` (premier envoi réussi).
- Le Tirage au sort fait passer à ``drawn`` (scellement) ; ``drawn`` -> ``drawn`` couvre le
  ``--force-retirage``.
- La Révélation fait passer ``drawn`` à ``revealed``.

Ce module n'importe ``database`` qu'à l'appel, afin que ``database`` puisse en dépendre (schéma SQL).
"""

import sqlite3
from datetime import date
from enum import Enum
from pathlib import Path


class StatutEdition(Enum):
    DRAFT = "draft"
    ANNOUNCED = "announced"
    DRAWN = "drawn"
    REVEALED = "revealed"


class TransitionEditionInterdite(Exception):
    """Levée quand une transition de statut d'Édition n'est pas permise."""


TRANSITIONS_PERMISES: frozenset[tuple[StatutEdition, StatutEdition]] = frozenset(
    {
        (StatutEdition.DRAFT, StatutEdition.ANNOUNCED),
        (StatutEdition.ANNOUNCED, StatutEdition.DRAWN),
        (StatutEdition.DRAWN, StatutEdition.REVEALED),
        (StatutEdition.DRAWN, StatutEdition.DRAWN),
    }
)

STATUTS_SCELLES: frozenset[StatutEdition] = frozenset({StatutEdition.DRAWN, StatutEdition.REVEALED})

STATUTS_SQL: str = ", ".join(f"'{s.value}'" for s in StatutEdition)


def est_scellee(statut_edition: StatutEdition) -> bool:
    """Vrai quand le Tirage au sort est scellé (Bénéficiaires figés, présences verrouillées)."""
    return statut_edition in STATUTS_SCELLES


def _ouvrir(conn_or_path: sqlite3.Connection | Path | str) -> tuple[sqlite3.Connection, bool]:
    if isinstance(conn_or_path, sqlite3.Connection):
        return conn_or_path, False
    from .database import get_db_connection

    return get_db_connection(conn_or_path), True


def statut(conn_or_path: sqlite3.Connection | Path | str, year: int) -> StatutEdition:
    """Statut de l'Édition `year` ; une Édition absente est considérée comme `draft`."""
    conn, owned = _ouvrir(conn_or_path)
    try:
        row = conn.execute("SELECT status FROM editions WHERE year = ?;", (year,)).fetchone()
    finally:
        if owned:
            conn.close()
    return StatutEdition(row[0]) if row else StatutEdition.DRAFT


def creer_si_absente(conn: sqlite3.Connection, year: int) -> None:
    """Crée l'Édition en `draft` si elle n'existe pas (sans valider la transaction de l'appelant)."""
    conn.execute("INSERT OR IGNORE INTO editions (year, status) VALUES (?, ?);", (year, StatutEdition.DRAFT.value))


def avancer(conn: sqlite3.Connection, year: int, vers: StatutEdition) -> None:
    """Fait avancer l'Édition vers `vers`, ou lève `TransitionEditionInterdite`.

    N'effectue aucun commit : la modification participe à la transaction de l'appelant.
    """
    courant = statut(conn, year)
    if (courant, vers) not in TRANSITIONS_PERMISES:
        raise TransitionEditionInterdite(
            f"Transition d'Édition interdite pour {year} : '{courant.value}' -> '{vers.value}'."
        )
    conn.execute(
        """
        INSERT INTO editions (year, status) VALUES (?, ?)
        ON CONFLICT(year) DO UPDATE SET status = excluded.status;
        """,
        (year, vers.value),
    )


def sceller(conn: sqlite3.Connection, year: int) -> None:
    """Scelle le Tirage au sort : passe l'Édition à `drawn`.

    Un tirage sans Annonce préalable enchaîne `draft` -> `announced` -> `drawn`.
    """
    if statut(conn, year) is StatutEdition.DRAFT:
        avancer(conn, year, StatutEdition.ANNOUNCED)
    avancer(conn, year, StatutEdition.DRAWN)


def annee_courante(conn_or_path: sqlite3.Connection | Path | str) -> int:
    """Année de l'Édition la plus récente, ou année de l'horloge si la base est vide ou absente."""
    if not isinstance(conn_or_path, sqlite3.Connection) and not Path(conn_or_path).exists():
        return date.today().year
    conn, owned = _ouvrir(conn_or_path)
    try:
        row = conn.execute("SELECT MAX(year) FROM editions;").fetchone()
    except sqlite3.OperationalError:
        return date.today().year
    finally:
        if owned:
            conn.close()
    return int(row[0]) if row and row[0] is not None else date.today().year
