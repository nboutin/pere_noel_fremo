from pathlib import Path

from .campagne import (
    BASE_URL_PAR_DEFAUT,
    EXPEDITEUR_PAR_DEFAUT,
    Cta,
    Expediteur,
    ExpediteurGmail,
    Rendu,
    avancer_edition,
    avec_adresses_de_repli,
    charger_gabarit,
    charger_secure_data,
    cibler,
    envoyer_campagne,
    rendre_gabarit,
)
from .database import get_lutins
from .edition import StatutEdition, annee_courante
from .gabarits import DEFAULT_ANNONCE_TEMPLATE

CTA = Cta("Accéder à mon Espace Lutin", "#b30000")


def format_annonce_body(template: str, fullname: str, magic_url: str, year: int) -> str:
    """Injecte le nom, l'année et le Lien magique dans le modèle d'email d'Annonce."""
    return rendre_gabarit(template, fullname, magic_url, year, CTA)


def format_annonce_text(fullname: str, magic_url: str, year: int) -> str:
    """Génère la version texte brut (plain text) de l'email d'Annonce avec salutation et Lien magique."""
    return (
        f"HOHOHO {fullname},\n\n"
        f"L'atelier du Pôle Nord ouvre officiellement ses portes pour l'édition {year} du Père Noël de la Frémo !\n\n"
        "Accède dès maintenant à ton Espace Lutin personnel pour confirmer ta présence "
        f"et participer au Défi du lutin :\n"
        f"{magic_url}\n\n"
        f"Ce lien est magique et strictement personnel (aucun mot de passe requis).\n\n"
        f"Le Père Noël de la Frémo 🎅"
    )


def send_annonces(
    db_path: Path | str,
    secure_data_path: Path | str,
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
) -> dict[str, int]:
    """Exécute la Campagne d'Annonce aux Lutins actifs et consigne l'état d'envoi en base.

    Après le premier envoi réussi, l'Édition passe de `draft` à `announced` (jamais en simulation).
    """
    if year is None:
        year = annee_courante(db_path)
    secure_data = charger_secure_data(secure_data_path)
    gabarit = charger_gabarit(DEFAULT_ANNONCE_TEMPLATE, template_path)
    annee = year
    rendu = Rendu(
        objet=subject or f"🎅 [Père Noël de la Frémo {year}] Ton Espace Lutin est ouvert !",
        html=lambda nom, lien: format_annonce_body(gabarit, nom, lien, annee),
        texte=lambda nom, lien: format_annonce_text(nom, lien, annee),
    )
    sender = secure_data.get("sender_email", EXPEDITEUR_PAR_DEFAUT)
    expediteur = expediteur or ExpediteurGmail(sender, "l'Annonce", interactive=interactive_auth)

    absents_set = set(absents or []) | set(skip or [])

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
    if not simulation and bilan.nominal and bilan.envoyes > 0:
        avancer_edition(db_path, year, StatutEdition.DRAFT, StatutEdition.ANNOUNCED)

    return {
        "total": len(lutins),
        "sent": bilan.envoyes,
        "absents": absents_count,
        "sans_email": bilan.sans_email,
        "echecs": bilan.echecs,
    }
