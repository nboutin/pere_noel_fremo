"""Couche de données et logique métier pour l'Espace Admin.

Fournit l'agrégation synthétique de l'état d'avancement d'une Édition (présences,
liens magiques/tokens, progression au Défi du lutin) dans le respect strict du principe
d'Admin aveugle (ADR-0005, ADR-0013) : aucune consultation de la table `attributions`
et aucune fuite de couples Donneur-Bénéficiaire.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .database import connection


class StatutPresenceAdmin(str, Enum):
    """Statut de présence d'un Lutin à l'Édition."""

    CONFIRME = "confirme"
    ABSENT = "absent"
    EN_ATTENTE = "en_attente"


class StatutDefi(str, Enum):
    """Progression d'un Lutin au Défi du lutin."""

    NON_COMMENCE = "non_commence"
    EN_COURS = "en_cours"
    RESOLU = "resolu"
    ABANDONNE = "abandonne"


@dataclass(frozen=True)
class SuiviPresence:
    """Présence d'un Lutin pour l'Édition."""

    statut: StatutPresenceAdmin


@dataclass(frozen=True)
class SuiviLienMagique:
    """Lien magique (token) d'un Lutin pour l'Édition."""

    token: str
    sent_at: str | None

    @property
    def sent(self) -> bool:
        return self.sent_at is not None


@dataclass(frozen=True)
class SuiviDefi:
    """Progression d'un Lutin au Défi du lutin pour l'Édition."""

    statut: StatutDefi
    manches_resolues: int
    time_seconds: float | None
    best_time_seconds: float | None
    attempts: int
    pseudo_lutin: str | None


@dataclass(frozen=True)
class LutinSuivi:
    """Ligne de suivi d'un Lutin dans l'Espace Admin."""

    id: str
    fullname: str
    email: str
    is_active: bool
    presence: SuiviPresence
    lien_magique: SuiviLienMagique | None
    defi: SuiviDefi


@dataclass(frozen=True)
class MetriquesEdition:
    """Métriques globales (Lutins actifs, sauf `total_inscrits`)."""

    total_lutins: int
    confirmes: int
    absents: int
    en_attente: int
    liens_magiques_envoyes: int
    defi_resolus: int
    taux_resolution_defi: float
    total_inscrits: int
    inactifs: int


@dataclass(frozen=True)
class SyntheseEdition:
    """Synthèse de l'état d'avancement d'une Édition pour l'Espace Admin."""

    year: int
    status: str
    date_repas: str | None
    available_years: list[int]
    metrics: MetriquesEdition
    lutins: list[LutinSuivi]


def _suivi_defi(scores: list[sqlite3.Row]) -> SuiviDefi:
    solved = [s for s in scores if s["solved"]]
    times = [float(s["time_seconds"]) for s in solved if s["time_seconds"] is not None]
    if solved:
        statut = StatutDefi.RESOLU
    elif any(s["started_at"] is not None and s["completed_at"] is None for s in scores):
        statut = StatutDefi.EN_COURS
    elif any(s["completed_at"] is not None for s in scores):
        statut = StatutDefi.ABANDONNE
    else:
        statut = StatutDefi.NON_COMMENCE
    return SuiviDefi(
        statut=statut,
        manches_resolues=len(solved),
        time_seconds=sum(times) if solved else None,
        best_time_seconds=min(times) if times else None,
        attempts=sum(int(s["attempts"] or 0) for s in scores),
        pseudo_lutin=str(scores[0]["pseudo_lutin"]) if scores and scores[0]["pseudo_lutin"] else None,
    )


def get_admin_edition_summary(
    db_path: Path | str | sqlite3.Connection,
    year: int,
) -> SyntheseEdition:
    """Agrège l'état d'avancement complet d'une Édition pour l'Espace Admin.

    Respecte scrupuleusement l'Admin aveugle :
    - La table `attributions` n'est JAMAIS requêtée.
    - Aucun couple Donneur-Bénéficiaire n'est exposé.

    Args:
        db_path: Chemin du fichier SQLite ou connexion SQLite ouverte.
        year: Année de l'Édition cible.

    Returns:
        Synthèse typée contenant les métriques globales et la liste détaillée des Lutins.
    """
    with connection(db_path) as conn:
        ed_row = conn.execute(
            "SELECT year, status, date_repas FROM editions WHERE year = ?;",
            (year,),
        ).fetchone()

        status = str(ed_row["status"]) if ed_row and ed_row["status"] else "draft"
        date_repas = str(ed_row["date_repas"]) if ed_row and ed_row["date_repas"] else None

        all_editions_rows = conn.execute("SELECT year FROM editions ORDER BY year DESC;").fetchall()
        available_years = [int(r["year"]) for r in all_editions_rows]
        if year not in available_years:
            available_years.append(year)
            available_years.sort(reverse=True)

        lutin_rows = conn.execute(
            "SELECT id, fullname, email, is_active FROM lutins ORDER BY fullname COLLATE NOCASE ASC;"
        ).fetchall()

        presences_map = {
            row["lutin_id"]: row["present"]
            for row in conn.execute("SELECT lutin_id, present FROM presences WHERE year = ?;", (year,))
        }
        tokens_map = {
            row["lutin_id"]: row
            for row in conn.execute("SELECT lutin_id, token, sent_at FROM tokens WHERE year = ?;", (year,))
        }

        scores_by_lutin: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for s in conn.execute(
            """
            SELECT lutin_id, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            FROM scores_defi
            WHERE year = ?
            ORDER BY lutin_id, manche_id ASC;
            """,
            (year,),
        ):
            scores_by_lutin[s["lutin_id"]].append(s)

        lutins: list[LutinSuivi] = []
        for l_row in lutin_rows:
            lid = str(l_row["id"])
            if lid not in presences_map:
                presence = StatutPresenceAdmin.EN_ATTENTE
            elif presences_map[lid] == 1:
                presence = StatutPresenceAdmin.CONFIRME
            else:
                presence = StatutPresenceAdmin.ABSENT

            t_row = tokens_map.get(lid)
            lien = (
                SuiviLienMagique(
                    token=str(t_row["token"]),
                    sent_at=str(t_row["sent_at"]) if t_row["sent_at"] else None,
                )
                if t_row
                else None
            )

            lutins.append(
                LutinSuivi(
                    id=lid,
                    fullname=str(l_row["fullname"]),
                    email=str(l_row["email"]) if l_row["email"] else "",
                    is_active=bool(l_row["is_active"]),
                    presence=SuiviPresence(statut=presence),
                    lien_magique=lien,
                    defi=_suivi_defi(scores_by_lutin.get(lid, [])),
                )
            )

        actifs = [lutin for lutin in lutins if lutin.is_active]
        defi_resolus = sum(1 for lutin in actifs if lutin.defi.statut is StatutDefi.RESOLU)
        metrics = MetriquesEdition(
            total_lutins=len(actifs),
            confirmes=sum(1 for lutin in actifs if lutin.presence.statut is StatutPresenceAdmin.CONFIRME),
            absents=sum(1 for lutin in actifs if lutin.presence.statut is StatutPresenceAdmin.ABSENT),
            en_attente=sum(1 for lutin in actifs if lutin.presence.statut is StatutPresenceAdmin.EN_ATTENTE),
            liens_magiques_envoyes=sum(1 for lutin in actifs if lutin.lien_magique and lutin.lien_magique.sent),
            defi_resolus=defi_resolus,
            taux_resolution_defi=round(defi_resolus / len(actifs) * 100, 1) if actifs else 0.0,
            total_inscrits=len(lutins),
            inactifs=len(lutins) - len(actifs),
        )

        return SyntheseEdition(
            year=year,
            status=status,
            date_repas=date_repas,
            available_years=available_years,
            metrics=metrics,
            lutins=lutins,
        )
