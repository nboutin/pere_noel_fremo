"""Parcours de manche : déroulé chronométré unique d'un Lutin sur une Manche (démarrage, Soumission, abandon).

Chaque appel ouvre une connexion et une transaction `BEGIN IMMEDIATE` uniques qui enchaînent les gardes
(présence, déverrouillage, validité de la grille, état du score) puis l'écriture. Les règles de la Soumission
(complétude, plafond d'essais, pénalité, scellement) vivent ici ; les couches HTTP se contentent de traduire
le statut retourné.
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
    get_lutin_pseudo,
    get_or_assign_pseudo,
    get_score_defi,
    parse_iso_or_legacy,
    start_score_defi,
)
from .defi import (
    MAX_ESSAIS_PAR_MANCHE,
    PENALITE_ESSAI_FAUX_SECONDES,
    GrilleInvalideError,
    get_manche_attributes,
    is_manche_unlocked,
    is_solution_complete,
    validate_grille_solution,
)


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


class StatutSoumission(Enum):
    """Issue d'une Soumission de solution sur une Manche."""

    RESOLUE = "resolue"
    FAUSSE = "fausse"
    SCELLEE = "scellee"
    INCOMPLETE = "incomplete"
    DEJA_TERMINEE = "deja_terminee"
    NON_DEMARRE = "non_demarre"
    PRESENCE_REQUISE = "presence_requise"
    MANCHE_INTROUVABLE = "manche_introuvable"
    MANCHE_VERROUILLEE = "manche_verrouillee"


@dataclass(frozen=True)
class ResultatSoumission:
    """Résultat d'une Soumission ; les compteurs reflètent l'état du score après l'opération.

    `penalite_cumulee_secondes` vaut 15 s par Soumission fausse enregistrée (c'est la pénalité qui s'ajoute
    au temps officiel) ; `time_seconds` n'est renseigné que pour une manche `RESOLUE`.
    """

    statut: StatutSoumission
    attempts: int = 0
    essais_restants: int = MAX_ESSAIS_PAR_MANCHE
    essais_max: int = MAX_ESSAIS_PAR_MANCHE
    penalite_essai_secondes: int = PENALITE_ESSAI_FAUX_SECONDES
    penalite_cumulee_secondes: int = 0
    time_seconds: float | None = None
    pseudo_lutin: str | None = None


class StatutManche(Enum):
    """Statut d'une Manche pour un Lutin, tel que dérivé du Parcours."""

    RESOLUE = "resolue"
    ABANDONNEE = "abandonnee"
    SCELLEE = "scellee"
    DISPONIBLE = "disponible"
    EN_COURS = "en_cours"
    VERROUILLEE = "verrouillee"


@dataclass(frozen=True)
class EtatParcours:
    """État d'un Lutin sur une Manche : statut et compteurs du score (valeurs neutres si jamais démarrée)."""

    manche_id: int
    statut: StatutManche
    attempts: int = 0
    time_seconds: float | None = None
    pseudo_lutin: str | None = None


def statut_score(score: dict[str, Any], unlocked: bool = True) -> StatutManche:
    """Dérive le statut d'une Manche d'une ligne de score (vide ou absente si jamais démarrée).

    Une manche terminée sans résolution est `SCELLEE` si le plafond d'essais est atteint, `ABANDONNEE` sinon.
    """
    if score.get("solved"):
        return StatutManche.RESOLUE
    if score.get("completed_at") is not None:
        if int(score.get("attempts") or 0) >= MAX_ESSAIS_PAR_MANCHE:
            return StatutManche.SCELLEE
        return StatutManche.ABANDONNEE
    if score.get("started_at") is not None:
        return StatutManche.EN_COURS
    return StatutManche.DISPONIBLE if unlocked else StatutManche.VERROUILLEE


def etat(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    manches: list[dict[str, Any]],
    now: datetime,
) -> list[EtatParcours]:
    """État d'un Lutin sur chacune des manches données, lu en une seule requête."""
    if not manches:
        return []
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT manche_id, solved, attempts, time_seconds, started_at, completed_at, pseudo_lutin "
            "FROM scores_defi WHERE lutin_id = ? AND year = ?;",
            (lutin_id, year),
        ).fetchall()
    finally:
        conn.close()
    scores = {int(row["manche_id"]): dict(row) for row in rows}
    resultat: list[EtatParcours] = []
    for manche in manches:
        manche_id = int(manche["id"])
        score = scores.get(manche_id, {})
        resultat.append(
            EtatParcours(
                manche_id=manche_id,
                statut=statut_score(score, unlocked=is_manche_unlocked(manche, now=now)),
                attempts=int(score.get("attempts") or 0),
                time_seconds=score.get("time_seconds"),
                pseudo_lutin=score.get("pseudo_lutin"),
            )
        )
    return resultat


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


def soumettre(
    db_path: Path | str,
    lutin_id: str,
    year: int,
    manche: dict[str, Any] | None,
    solution: dict[str, Any],
    now: datetime,
) -> ResultatSoumission:
    """Enregistre la Soumission d'un Lutin : complétude, validation, plafond d'essais, pénalité et scellement."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            begin_immediate(conn)
            acces = _garde_acces(conn, lutin_id, year, manche, now)
            if isinstance(acces, ResultatParcours):
                return ResultatSoumission(StatutSoumission[acces.statut.name])
            manche = acces
            manche_id = int(manche["id"])

            score = get_score_defi(conn, lutin_id, year, manche_id=manche_id)
            attempts = int(score.get("attempts") or 0)
            pseudo = score.get("pseudo_lutin") or get_lutin_pseudo(conn, lutin_id, year)
            if score.get("completed_at"):
                return _resultat(StatutSoumission.DEJA_TERMINEE, attempts, pseudo)
            if not score.get("started_at"):
                return ResultatSoumission(StatutSoumission.NON_DEMARRE)

            # Seules les Soumissions complètes consomment un essai (ADR-0007).
            if not is_solution_complete(manche, solution):
                return _resultat(StatutSoumission.INCOMPLETE, attempts, pseudo)

            attempts += 1
            now_str = now.isoformat()
            if validate_grille_solution(manche, solution):
                brut = (now - parse_iso_or_legacy(str(score["started_at"]))).total_seconds()
                temps = max(0.1, round(brut + (attempts - 1) * PENALITE_ESSAI_FAUX_SECONDES, 1))
                conn.execute(
                    "UPDATE scores_defi SET solved = 1, attempts = ?, time_seconds = ?, completed_at = ? "
                    "WHERE lutin_id = ? AND year = ? AND manche_id = ?;",
                    (attempts, temps, now_str, lutin_id, year, manche_id),
                )
                return _resultat(StatutSoumission.RESOLUE, attempts, pseudo, fausses=attempts - 1, time_seconds=temps)

            if attempts >= MAX_ESSAIS_PAR_MANCHE:
                conn.execute(
                    "UPDATE scores_defi SET solved = 0, attempts = ?, time_seconds = NULL, completed_at = ? "
                    "WHERE lutin_id = ? AND year = ? AND manche_id = ?;",
                    (attempts, now_str, lutin_id, year, manche_id),
                )
                return _resultat(StatutSoumission.SCELLEE, attempts, pseudo, fausses=attempts)

            conn.execute(
                "UPDATE scores_defi SET attempts = ? WHERE lutin_id = ? AND year = ? AND manche_id = ?;",
                (attempts, lutin_id, year, manche_id),
            )
            return _resultat(StatutSoumission.FAUSSE, attempts, pseudo, fausses=attempts)
    finally:
        conn.close()


def _resultat(
    statut: StatutSoumission,
    attempts: int,
    pseudo: str | None,
    fausses: int = 0,
    time_seconds: float | None = None,
) -> ResultatSoumission:
    return ResultatSoumission(
        statut,
        attempts=attempts,
        essais_restants=max(0, MAX_ESSAIS_PAR_MANCHE - attempts),
        penalite_cumulee_secondes=fausses * PENALITE_ESSAI_FAUX_SECONDES,
        time_seconds=time_seconds,
        pseudo_lutin=pseudo,
    )
