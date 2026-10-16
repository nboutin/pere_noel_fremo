"""Couche de données et logique métier pour l'Espace Admin.

Fournit l'agrégation synthétique de l'état d'avancement d'une Édition (présences,
liens magiques/tokens, progression au Défi du lutin) dans le respect strict du principe
d'Admin aveugle (ADR-0005, ADR-0013) : aucune consultation de la table `attributions`
et aucune fuite de couples Donneur-Bénéficiaire.
"""

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from .database import connection


class PresenceInfo(dict[str, Any]):
    """Informations de présence d'un Lutin avec accès dictionnaire et comparaison par statut."""

    @property
    def statut(self) -> str:
        return str(self.get("statut") or "")

    @property
    def label(self) -> str:
        return str(self.get("label") or "")

    @property
    def present(self) -> bool | None:
        return self.get("present")

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return self.get("statut") == other
        return super().__eq__(other)

    def __str__(self) -> str:
        return self.statut


class TokenInfo(dict[str, Any]):
    """Informations sur le Lien magique / Token d'un Lutin avec compatibilité string et dict."""

    @property
    def token(self) -> str | None:
        val = self.get("token")
        return str(val) if val is not None else None

    @property
    def sent(self) -> bool:
        return bool(self.get("sent"))

    @property
    def sent_at(self) -> str | None:
        val = self.get("sent_at")
        return str(val) if val is not None else None

    def __bool__(self) -> bool:
        return self.get("token") is not None

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return self.get("token") == other
        if other is None:
            return self.get("token") is None
        return super().__eq__(other)

    def __str__(self) -> str:
        return str(self.get("token") or "")


class DefiInfo(dict[str, Any]):
    """Progression au Défi du lutin avec accès attributs et comparaison par statut."""

    @property
    def statut(self) -> str:
        return str(self.get("statut") or "")

    @property
    def label(self) -> str:
        return str(self.get("label") or "")

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return self.get("statut") == other
        return super().__eq__(other)

    def __str__(self) -> str:
        return self.statut


def get_admin_edition_summary(
    db_path: Path | str | sqlite3.Connection,
    year: int,
    res_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Agrège l'état d'avancement complet d'une Édition pour l'Espace Admin.

    Respecte scrupuleusement l'Admin aveugle :
    - La table `attributions` n'est JAMAIS requêtée.
    - Aucun couple Donneur-Bénéficiaire n'est exposé.

    Args:
        db_path: Chemin du fichier SQLite ou connexion SQLite ouverte.
        year: Année de l'Édition cible.
        res_dir: Répertoire optionnel des ressources (`res/`).

    Returns:
        Dictionnaire contenant les métriques globales et la liste détaillée des Lutins.
    """
    with connection(db_path) as conn:
        # 1. Informations de l'édition demandée et liste des éditions disponibles
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

        # 2. Lutins enregistrés (triés par fullname ASC)
        lutin_rows = conn.execute(
            "SELECT id, fullname, email, is_active FROM lutins ORDER BY fullname COLLATE NOCASE ASC;"
        ).fetchall()

        # 3. Présences pour l'année
        presence_rows = conn.execute(
            "SELECT lutin_id, present, updated_at FROM presences WHERE year = ?;",
            (year,),
        ).fetchall()
        presences_map = {row["lutin_id"]: row for row in presence_rows}

        # 4. Tokens / Liens magiques pour l'année
        token_rows = conn.execute(
            "SELECT lutin_id, token, sent_at FROM tokens WHERE year = ?;",
            (year,),
        ).fetchall()
        tokens_map = {row["lutin_id"]: row for row in token_rows}

        # 5. Scores Défi du lutin pour l'année
        score_rows = conn.execute(
            """
            SELECT lutin_id, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            FROM scores_defi
            WHERE year = ?
            ORDER BY lutin_id, manche_id ASC;
            """,
            (year,),
        ).fetchall()
        scores_by_lutin: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for s in score_rows:
            scores_by_lutin[s["lutin_id"]].append(s)

        # 6. Agrégation par Lutin
        lutin_items: list[dict[str, Any]] = []

        total_active_lutins = 0
        count_confirmes = 0
        count_absents = 0
        count_en_attente = 0
        count_tokens_envoyes = 0
        count_defi_resolus = 0

        for l_row in lutin_rows:
            lid = str(l_row["id"])
            fullname = str(l_row["fullname"])
            email = str(l_row["email"]) if l_row["email"] else ""
            is_active = bool(l_row["is_active"])

            # Statut présence
            if lid in presences_map:
                is_pres = presences_map[lid]["present"]
                if is_pres == 1:
                    p_statut = "confirme"
                    p_label = "Confirmé"
                    p_val = True
                else:
                    p_statut = "absent"
                    p_label = "Absent"
                    p_val = False
            else:
                p_statut = "en_attente"
                p_label = "En attente"
                p_val = None

            presence_info = PresenceInfo(
                statut=p_statut,
                label=p_label,
                present=p_val,
            )

            # Statut token / lien magique
            if lid in tokens_map:
                t_row = tokens_map[lid]
                t_val = str(t_row["token"]) if t_row["token"] else None
                sent_at = str(t_row["sent_at"]) if t_row["sent_at"] else None
                is_sent = sent_at is not None
                token_info: TokenInfo | None = TokenInfo(
                    token=t_val,
                    value=t_val,
                    sent=is_sent,
                    sent_at=sent_at,
                )
            else:
                t_val = None
                sent_at = None
                is_sent = False
                token_info = None

            safe_token_info = TokenInfo(
                token=t_val,
                value=t_val,
                sent=is_sent,
                sent_at=sent_at,
            )

            # Statut Défi du lutin
            l_scores = scores_by_lutin.get(lid, [])
            solved_manches = [s for s in l_scores if s["solved"]]
            solved_count = len(solved_manches)
            times = [float(s["time_seconds"]) for s in solved_manches if s["time_seconds"] is not None]
            total_time = sum(times) if times else 0.0
            best_time = min(times) if times else None
            total_attempts = sum(int(s["attempts"] or 0) for s in l_scores)
            pseudo_lutin = str(l_scores[0]["pseudo_lutin"]) if l_scores and l_scores[0]["pseudo_lutin"] else None

            if solved_count > 0:
                d_statut = "resolu"
                d_label = "Résolu"
            elif any(s["started_at"] is not None and s["completed_at"] is None for s in l_scores):
                d_statut = "en_cours"
                d_label = "En cours"
            elif any(s["completed_at"] is not None and not s["solved"] for s in l_scores):
                d_statut = "abandonne"
                d_label = "Abandonné"
            else:
                d_statut = "non_commence"
                d_label = "Non commencé"

            defi_info = DefiInfo(
                statut=d_statut,
                label=d_label,
                manches_resolues=solved_count,
                solved_manches_count=solved_count,
                time_seconds=total_time if solved_count > 0 else None,
                total_time_seconds=total_time if solved_count > 0 else None,
                best_time_seconds=best_time,
                attempts=total_attempts,
                total_attempts=total_attempts,
                pseudo_lutin=pseudo_lutin,
            )

            # Comptabilisation des métriques globales (uniquement pour les Lutins actifs)
            if is_active:
                total_active_lutins += 1
                if p_statut == "confirme":
                    count_confirmes += 1
                elif p_statut == "absent":
                    count_absents += 1
                else:
                    count_en_attente += 1

                if is_sent:
                    count_tokens_envoyes += 1

                if d_statut == "resolu":
                    count_defi_resolus += 1

            lutin_items.append(
                {
                    "id": lid,
                    "fullname": fullname,
                    "email": email,
                    "is_active": is_active,
                    "presence": presence_info,
                    "presence_statut": p_statut,
                    "presence_label": p_label,
                    "token": token_info,
                    "token_info": safe_token_info,
                    "tokens": safe_token_info,
                    "token_value": t_val,
                    "token_sent": is_sent,
                    "token_sent_at": sent_at,
                    "magic_link": f"/lutin/{t_val}" if t_val else None,
                    "url": f"/lutin/{t_val}" if t_val else None,
                    "defi": defi_info,
                    "defi_statut": d_statut,
                    "defi_label": d_label,
                }
            )

        # Calcul du taux de résolution
        taux_resolution = round((count_defi_resolus / total_active_lutins) * 100, 1) if total_active_lutins > 0 else 0.0

        metrics = {
            "total_lutins": total_active_lutins,
            "confirmes": count_confirmes,
            "absents": count_absents,
            "en_attente": count_en_attente,
            "tokens_envoyes": count_tokens_envoyes,
            "defi_resolus": count_defi_resolus,
            "taux_resolution_defi": taux_resolution,
            "total_inscrits": len(lutin_rows),
            "inactifs": len(lutin_rows) - total_active_lutins,
        }

        edition_info = {
            "year": year,
            "status": status,
            "date_repas": date_repas,
        }

        return {
            "year": year,
            "edition": edition_info,
            "status": status,
            "available_years": available_years,
            "metrics": metrics,
            "total_lutins": total_active_lutins,
            "confirmes": count_confirmes,
            "absents": count_absents,
            "en_attente": count_en_attente,
            "tokens_envoyes": count_tokens_envoyes,
            "defi_resolus": count_defi_resolus,
            "taux_resolution_defi": taux_resolution,
            "lutins": lutin_items,
        }
