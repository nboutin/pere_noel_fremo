"""Campagne d'Annonce de manche du Défi du lutin (voir ADR-0014).

Envoie à chaque Lutin actif un courriel notifiant le déblocage d'une nouvelle Grille logique
avec son Lien magique vers son Espace Lutin.
Cette campagne n'a aucun effet de transition sur le cycle de vie de l'Édition.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from .campagne import (
    BASE_URL_PAR_DEFAUT,
    EXPEDITEUR_PAR_DEFAUT,
    Cta,
    Expediteur,
    ExpediteurGmail,
    Rendu,
    avec_adresses_de_repli,
    charger_gabarit,
    charger_secure_data,
    cibler,
    envoyer_campagne,
    rendre_gabarit,
)
from .database import connection, enregistrer_manche_envoyee, est_manche_envoyee, get_lutins
from .defi import PARIS_TZ, _parse_unlock_at
from .edition import annee_courante
from .gabarits import DEFAULT_MANCHE_TEMPLATE

CTA = Cta("Relever le Défi sur mon Espace Lutin", "#2563eb")


def charger_infos_manche(manche_id: int, year: int, res_dir: Path | str = "res") -> dict[str, Any]:
    """Charge les métadonnées de la manche depuis res/{year}/grilles/manche_{id}.yml."""
    chemin = Path(res_dir) / str(year) / "grilles" / f"manche_{manche_id}.yml"
    if not chemin.exists():
        return {
            "id": manche_id,
            "title": f"Manche {manche_id}",
            "estimated_time": "2 à 5 minutes",
        }
    with open(chemin, encoding="utf-8") as stream:
        data: dict[str, Any] = yaml.safe_load(stream) or {}
    return {
        "id": data.get("id", manche_id),
        "title": data.get("title", f"Manche {manche_id}"),
        "estimated_time": data.get("estimated_time", "2 à 5 minutes"),
    }


def get_declared_absents(db_path: Path | str, year: int) -> set[str]:
    """Récupère les identifiants des Lutins ayant formellement décliné leur présence (present = 0)."""
    with connection(db_path) as conn:
        rows = conn.execute(
            "SELECT lutin_id FROM presences WHERE year = ? AND present = 0;",
            (year,),
        ).fetchall()
        return {str(r["lutin_id"]) for r in rows}


def trouver_manche_a_annoncer(
    db_path: Path | str,
    year: int,
    res_dir: Path | str = "res",
    max_age_hours: int = 72,
    now: datetime | None = None,
) -> int | None:
    """Identifie la manche la plus récente déverrouillée et non encore envoyée (ADR-0015).

    Seules les manches dont l'ouverture est échue (unlock_at <= now) et dans la fenêtre
    de rattrapage (now - unlock_at <= max_age_hours) sont candidates.
    """
    if now is None:
        now = datetime.now(PARIS_TZ)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=PARIS_TZ)

    candidats: list[tuple[int, datetime]] = []
    grilles_dir = Path(res_dir) / str(year) / "grilles"
    if not grilles_dir.exists():
        return None

    limite_age = now - timedelta(hours=max_age_hours)

    for fichier in sorted(grilles_dir.glob("manche_*.yml")):
        with open(fichier, encoding="utf-8") as stream:
            data = yaml.safe_load(stream) or {}
        manche_id = data.get("id")
        unlock_val = data.get("unlock_at")
        if not manche_id or not unlock_val:
            continue

        try:
            unlock_dt = _parse_unlock_at(unlock_val).astimezone(PARIS_TZ)
        except (ValueError, TypeError):
            continue

        if limite_age <= unlock_dt <= now and not est_manche_envoyee(db_path, year, int(manche_id)):
            candidats.append((int(manche_id), unlock_dt))

    if not candidats:
        return None

    # Sélectionner la manche la plus récemment déverrouillée
    candidats.sort(key=lambda c: (c[1], c[0]), reverse=True)
    return candidats[0][0]


def format_manche_body(
    template: str,
    fullname: str,
    magic_url: str,
    year: int,
    manche_id: int,
    manche_title: str,
    estimated_time: str,
) -> str:
    """Injecte les métadonnées de manche et le Lien magique dans le modèle HTML."""
    gabarit_personnalise = (
        template.replace("{manche_id}", str(manche_id))
        .replace("{manche_title}", manche_title)
        .replace("{estimated_time}", estimated_time)
    )
    return rendre_gabarit(gabarit_personnalise, fullname, magic_url, year, CTA)


def format_manche_text(
    fullname: str,
    magic_url: str,
    year: int,
    manche_id: int,
    manche_title: str,
    estimated_time: str,
) -> str:
    """Génère la version texte brut (plain text) de l'email d'Annonce de manche."""
    return (
        f"HOHOHO {fullname},\n\n"
        f"La cloche du Défi du lutin vient de sonner au Pôle Nord pour l'édition {year} !\n"
        f"Une nouvelle épreuve de déduction logique vient d'être déverrouillée : {manche_title}.\n\n"
        f"Durée estimée : {estimated_time}.\n\n"
        "Connecte-toi à ton Espace Lutin pour lancer ton chronomètre et relever le défi :\n"
        f"{magic_url}\n\n"
        "Rappel : les manches précédentes restent jouables à tout moment sans pénalité jusqu'au Repas de Noël.\n"
        "Et si ce n'est pas encore fait, pense à valider ta confirmation de présence avant le 1er novembre !\n\n"
        "Ce lien est magique et strictement personnel (aucun mot de passe requis).\n\n"
        "Le Père Noël de la Frémo 🎅"
    )


def send_annonces_manche(
    db_path: Path | str,
    secure_data_path: Path | str,
    manche_id: int,
    year: int | None = None,
    base_url: str | None = None,
    template_path: Path | str | None = None,
    subject: str | None = None,
    dry_run: bool = False,
    no_email: bool = False,
    absents: list[str] | None = None,
    skip: list[str] | None = None,
    target_lutins: list[str] | None = None,
    recipient_override: str | None = None,
    interactive_auth: bool = False,
    expediteur: Expediteur | None = None,
    res_dir: Path | str = "res",
) -> dict[str, int]:
    """Exécute la Campagne d'Annonce de manche aux Lutins actifs (hors Absents).

    Sans effet sur le cycle de vie de l'Édition.
    """
    if year is None:
        year = annee_courante(db_path)

    infos_manche = charger_infos_manche(manche_id, year, res_dir=res_dir)
    m_title = infos_manche["title"]
    m_time = infos_manche["estimated_time"]

    secure_data = charger_secure_data(secure_data_path)
    gabarit = charger_gabarit(DEFAULT_MANCHE_TEMPLATE, template_path)
    annee = year

    # Nettoyage de l'objet pour un rendu harmonieux
    if subject is None:
        subject = f"🧩 [Père Noël de la Frémo {year}] Défi du lutin : {m_title} !"

    rendu = Rendu(
        objet=subject,
        html=lambda nom, lien: format_manche_body(gabarit, nom, lien, annee, manche_id, m_title, m_time),
        texte=lambda nom, lien: format_manche_text(nom, lien, annee, manche_id, m_title, m_time),
    )

    sender = secure_data.get("sender_email", EXPEDITEUR_PAR_DEFAUT)
    expediteur = expediteur or ExpediteurGmail(sender, f"la {m_title}", interactive=interactive_auth)

    absents_set = set(absents or []) | set(skip or []) | get_declared_absents(db_path, year)

    lutins = avec_adresses_de_repli(get_lutins(db_path, active_only=True), secure_data)
    concernes = cibler(lutins, target_lutins)
    absents_count = sum(1 for k in concernes if k in absents_set)
    destinataires = {k: v for k, v in concernes.items() if k not in absents_set}

    simulation = dry_run or no_email
    bilan = envoyer_campagne(
        db_path,
        year,
        destinataires,
        rendu,
        expediteur,
        base_url=base_url or secure_data.get("base_url") or BASE_URL_PAR_DEFAUT,
        dry_run=simulation,
        override_email=recipient_override,
        cible=bool(target_lutins),
    )

    if not simulation and bilan.nominal and bilan.echecs == 0 and bilan.envoyes > 0:
        enregistrer_manche_envoyee(db_path, year, manche_id, bilan.envoyes)

    return {
        "total": len(lutins),
        "sent": bilan.envoyes,
        "failed": bilan.echecs,
        "absent": absents_count,
        "no_email": bilan.sans_email,
    }
