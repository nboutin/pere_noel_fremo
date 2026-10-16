"""Parcours de manche : déroulé chronométré unique d'un Lutin sur une Manche (démarrage, abandon).

Chaque appel ouvre une connexion et une transaction `BEGIN IMMEDIATE` uniques qui enchaînent les gardes
(présence, déverrouillage, validité de la grille, état du score) puis l'écriture. Les couches HTTP se
contentent de traduire le `StatutParcours` retourné.
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .database import (
    abandon_score_defi,
    begin_immediate,
    get_db_connection,
    get_lutin_presence,
    get_or_assign_pseudo,
    get_score_defi,
    start_score_defi,
)
from .defi import GrilleInvalideError, get_manche_attributes, is_manche_unlocked


class StatutParcours(Enum):
    """Issue d'une opération sur un Parcours de manche."""

    DEMARRE = "demarre"
    DEJA_RESOLUE = "deja_resolue"
    DEJA_TERMINEE = "deja_terminee"
    NON_DEMARRE = "non_demarre"
    PRESENCE_REQUISE = "presence_requise"
    MANCHE_INTROUVABLE = "manche_introuvable"
    MANCHE_VERROUILLEE = "manche_verrouillee"
    GRILLE_INVALIDE = "grille_invalide"
    ABANDONNE = "abandonne"


@dataclass(frozen=True)
class ResultatParcours:
    """Résultat d'une opération de Parcours ; les champs facultatifs dépendent du statut."""

    statut: StatutParcours
    pseudo_lutin: str | None = None
    started_at: str | None = None
    indices: list[str] = field(default_factory=list)
    detail: str | None = None


def _garde_acces(
    conn: sqlite3.Connection,
    lutin_id: str,
    year: int,
    manche: dict[str, Any] | None,
    now: datetime,
) -> ResultatParcours | dict[str, Any]:
    """Présence, existence puis déverrouillage de la manche ; retourne la manche si l'accès est autorisé."""
    if not get_lutin_presence(conn, lutin_id, year):
        return ResultatParcours(StatutParcours.PRESENCE_REQUISE)
    if manche is None:
        return ResultatParcours(StatutParcours.MANCHE_INTROUVABLE)
    if not is_manche_unlocked(manche, now=now):
        return ResultatParcours(StatutParcours.MANCHE_VERROUILLEE)
    return manche


def demarrer(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    manche: dict[str, Any] | None,
    now: datetime,
) -> ResultatParcours:
    """Démarre (ou reprend, de façon idempotente) le Parcours d'un Lutin sur une Manche."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            begin_immediate(conn)
            acces = _garde_acces(conn, lutin_id, year, manche, now)
            if isinstance(acces, ResultatParcours):
                return acces
            manche = acces
            manche_id = int(manche["id"])

            try:
                get_manche_attributes(manche)
            except GrilleInvalideError as exc:
                return ResultatParcours(StatutParcours.GRILLE_INVALIDE, detail=str(exc))

            pseudo = get_or_assign_pseudo(conn, lutin_id, year)
            existant = get_score_defi(conn, lutin_id, year, manche_id=manche_id)
            if existant.get("solved"):
                return ResultatParcours(StatutParcours.DEJA_RESOLUE, pseudo_lutin=pseudo)
            if existant.get("completed_at"):
                return ResultatParcours(StatutParcours.DEJA_TERMINEE, pseudo_lutin=pseudo)

            score = start_score_defi(conn, lutin_id, year, pseudo_lutin=pseudo, manche_id=manche_id, now=now)
            return ResultatParcours(
                StatutParcours.DEMARRE,
                pseudo_lutin=score.get("pseudo_lutin") or pseudo,
                started_at=score.get("started_at"),
                indices=list(manche.get("indices") or []),
            )
    finally:
        conn.close()


def abandonner(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    manche: dict[str, Any] | None,
    now: datetime,
) -> ResultatParcours:
    """Scelle l'abandon du Parcours d'un Lutin sur une Manche démarrée et non terminée."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            begin_immediate(conn)
            acces = _garde_acces(conn, lutin_id, year, manche, now)
            if isinstance(acces, ResultatParcours):
                return acces
            manche = acces
            manche_id = int(manche["id"])

            existant = get_score_defi(conn, lutin_id, year, manche_id=manche_id)
            if existant.get("completed_at"):
                return ResultatParcours(StatutParcours.DEJA_TERMINEE, pseudo_lutin=existant.get("pseudo_lutin"))
            if not existant.get("started_at"):
                return ResultatParcours(StatutParcours.NON_DEMARRE)

            score = abandon_score_defi(conn, lutin_id, year, manche_id=manche_id, now=now)
            return ResultatParcours(
                StatutParcours.ABANDONNE,
                pseudo_lutin=score.get("pseudo_lutin") or existant.get("pseudo_lutin"),
            )
    finally:
        conn.close()
