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
from .database import get_confirmed_lutins
from .edition import StatutEdition, annee_courante, est_scellee, statut
from .gabarits import DEFAULT_REVELATION_TEMPLATE

CTA = Cta("Accéder à mon Espace Lutin et découvrir mon Bénéficiaire", "#047857")


def format_revelation_body(template: str, fullname: str, lien_magique: str, year: int) -> str:
    """Injecte le nom, l'année et le Lien magique dans le modèle d'email de Révélation."""
    return rendre_gabarit(template, fullname, lien_magique, year, CTA)


def format_revelation_text(fullname: str, lien_magique: str, year: int) -> str:
    """Génère la version texte brut (plain text) de l'email de Révélation."""
    return (
        f"HOHOHO {fullname},\n\n"
        f"Le grand Tirage au sort de l'édition {year} du Père Noël de la Frémo a été réalisé !\n\n"
        "Connecte-toi à ton Espace Lutin pour dévoiler ton Bénéficiaire sous la Carte à gratter :\n"
        f"{lien_magique}\n\n"
        "Ce lien est magique et strictement personnel (aucun mot de passe requis).\n\n"
        "Le Père Noël de la Frémo 🎅"
    )


def send_revelations(
    db_path: Path | str,
    secure_data_path: Path | str,
    year: int | None = None,
    base_url: str | None = None,
    template_path: Path | str | None = None,
    subject: str | None = None,
    dry_run: bool = False,
    no_email: bool = False,
    target_lutins: list[str] | None = None,
    recipient_override: str | None = None,
    expediteur: Expediteur | None = None,
) -> dict[str, int]:
    """Exécute la Campagne de Révélation aux Lutins confirmés et passe l'Édition à 'revealed'."""
    # Contrôle d'intégrité : refus strict si l'Édition n'est pas scellée (statuts définis par `edition`)
    if year is None:
        year = annee_courante(db_path)
    status = statut(db_path, year)
    if not est_scellee(status):
        attendus = " ou ".join(f"'{s.value}'" for s in StatutEdition if est_scellee(s))
        raise ValueError(
            f"Impossible d'envoyer la Révélation : l'édition {year} a le statut '{status.value}', "
            f"elle doit être {attendus}."
        )

    secure_data = charger_secure_data(secure_data_path)
    gabarit = charger_gabarit(DEFAULT_REVELATION_TEMPLATE, template_path)
    annee = year
    rendu = Rendu(
        objet=subject or f"🎅 [Père Noël de la Frémo {year}] Le Tirage au sort a eu lieu ! Découvre ton Bénéficiaire",
        html=lambda nom, lien: format_revelation_body(gabarit, nom, lien, annee),
        texte=lambda nom, lien: format_revelation_text(nom, lien, annee),
    )
    sender = secure_data.get("sender_email", EXPEDITEUR_PAR_DEFAUT)
    expediteur = expediteur or ExpediteurGmail(sender, "Révélation")

    confirmes = avec_adresses_de_repli(get_confirmed_lutins(db_path, year), secure_data)
    destinataires = cibler(confirmes, target_lutins)

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

    # Transition du statut de l'édition : 'revealed' sur envoi nominal uniquement
    if not simulation and bilan.nominal and bilan.echecs == 0 and bilan.envoyes > 0:
        avancer_edition(db_path, year, StatutEdition.DRAWN, StatutEdition.REVEALED)

    return {
        "total": len(confirmes),
        "sent": bilan.envoyes,
        "sans_email": bilan.sans_email,
        "echecs": bilan.echecs,
    }
