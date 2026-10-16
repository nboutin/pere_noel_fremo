"""Campagne : envoi groupé d'un courriel officiel (Annonce ou Révélation) à un ensemble de Lutins.

Une seule boucle d'envoi sert les deux campagnes ; elle ne connaît que le port `Expediteur`.
`ExpediteurGmail` est l'adaptateur de production, `ExpediteurMemoire` celui des tests.
"""

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from . import helper
from .database import get_db_connection
from .edition import StatutEdition, avancer, statut
from .tokens import build_lien_magique_url, create_or_get_token, mark_token_sent

logger = logging.getLogger(__name__)

EXPEDITEUR_PAR_DEFAUT = "leperenoeldelafremo@gmail.com"
BASE_URL_PAR_DEFAUT = "http://localhost:8000"


class Expediteur(Protocol):
    """Port d'envoi d'un courriel ; lève `helper.EmailSendError` en cas d'échec."""

    def envoyer(self, destinataire: str, objet: str, html: str, texte: str) -> None: ...


class ExpediteurGmail:
    """Adaptateur de production : le service Gmail est construit une seule fois, au premier envoi."""

    def __init__(self, sender_email: str, libelle: str, interactive: bool = False) -> None:
        self._sender_email = sender_email
        self._libelle = libelle
        self._interactive = interactive
        self._construit = False
        self._service: Any = None
        self._erreur: Exception | None = None

    def envoyer(self, destinataire: str, objet: str, html: str, texte: str) -> None:
        if not self._construit:
            self._service, self._erreur = helper.try_build_gmail_service(self._libelle, interactive=self._interactive)
            self._construit = True
        if self._erreur is not None:
            raise helper.EmailSendError("Service Gmail indisponible") from self._erreur
        helper.gmail_send_email(
            self._service,
            sender_email=self._sender_email,
            subject=objet,
            body=html,
            toaddr=destinataire,
            text_body=texte,
        )


@dataclass(frozen=True)
class MessageEnvoye:
    destinataire: str
    objet: str
    html: str
    texte: str


@dataclass
class ExpediteurMemoire:
    """Adaptateur de test : garde les messages et simule un échec pour certaines adresses."""

    echouer_pour: Iterable[str] = ()
    messages: list[MessageEnvoye] = field(default_factory=list)

    def envoyer(self, destinataire: str, objet: str, html: str, texte: str) -> None:
        if destinataire in set(self.echouer_pour):
            raise helper.EmailSendError("Échec simulé")
        self.messages.append(MessageEnvoye(destinataire, objet, html, texte))


@dataclass(frozen=True)
class Rendu:
    """Ce qui est propre à une campagne : objet et corps (HTML, avec échappement du nom, et texte)."""

    objet: str
    html: Callable[[str, str], str]  # (nom complet, Lien magique) -> HTML
    texte: Callable[[str, str], str]  # (nom complet, Lien magique) -> texte brut


@dataclass(frozen=True)
class BilanCampagne:
    envoyes: int
    sans_email: int
    echecs: int


def charger_secure_data(secure_data_path: Path | str) -> dict[str, Any]:
    chemin = Path(secure_data_path)
    if not chemin.exists():
        return {}
    with open(chemin, encoding="utf-8") as stream:
        data: dict[str, Any] = yaml.safe_load(stream) or {}
    return data


def charger_gabarit(defaut: str, template_path: Path | str | None) -> str:
    if template_path is not None and Path(template_path).exists():
        return Path(template_path).read_text(encoding="utf-8")
    return defaut


def avec_adresses_de_repli(
    lutins: Mapping[str, dict[str, Any]], secure_data: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Complète l'adresse manquante d'un Lutin par celle de `secure_data["personnes"]`."""
    personnes = secure_data.get("personnes") or {}
    resultat: dict[str, dict[str, Any]] = {}
    for lutin_id, params in lutins.items():
        email = params.get("email") or (personnes.get(lutin_id) or {}).get("email")
        resultat[lutin_id] = {**params, "email": email}
    return resultat


def cibler(lutins: Mapping[str, dict[str, Any]], cibles: Iterable[str] | None) -> dict[str, dict[str, Any]]:
    """Restreint aux Lutins ciblés ; sans cible, tous les Lutins sont conservés."""
    voulus = set(cibles or [])
    return {k: v for k, v in lutins.items() if not voulus or k in voulus}


def avancer_edition(db_path: Path | str, year: int, depuis: StatutEdition, vers: StatutEdition) -> None:
    """Fait passer l'Édition de `depuis` à `vers` ; sans effet si elle est dans un autre statut."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            if statut(conn, year) is depuis:
                avancer(conn, year, vers)
    finally:
        conn.close()


def envoyer_campagne(
    db_path: Path | str,
    year: int,
    destinataires: Mapping[str, dict[str, Any]],
    rendu: Rendu,
    expediteur: Expediteur,
    *,
    base_url: str = BASE_URL_PAR_DEFAUT,
    dry_run: bool = False,
    override_email: str | None = None,
) -> BilanCampagne:
    """Boucle unique d'envoi : Lien magique, rendu, envoi, `sent_at` et compteurs.

    En `dry_run`, jeton et rendu sont préparés mais rien n'est envoyé ni marqué.
    Un échec d'envoi n'interrompt pas les autres destinataires.
    """
    envoyes = sans_email = echecs = 0
    for lutin_id, params in destinataires.items():
        token = create_or_get_token(db_path, lutin_id, year)
        lien = build_lien_magique_url(base_url, token)
        nom = params.get("fullname", lutin_id)
        html = rendu.html(nom, lien)
        texte = rendu.texte(nom, lien)

        adresse = override_email or params.get("email")
        if not adresse:
            sans_email += 1
            logger.warning(f"Lutin '{lutin_id}' n'a pas d'adresse courriel configurée.")
            continue

        if dry_run:
            envoyes += 1
            continue

        try:
            expediteur.envoyer(adresse, rendu.objet, html, texte)
            mark_token_sent(db_path, token)
            envoyes += 1
        except helper.EmailSendError as exc:
            echecs += 1
            logger.error(f"Échec de l'envoi au Lutin '{lutin_id}' ({helper.mask_email(adresse)}): {exc}")
        except Exception as exc:
            echecs += 1
            logger.error(
                f"Erreur inattendue lors de l'envoi au Lutin '{lutin_id}' ({helper.mask_email(adresse)}): {exc}"
            )

    return BilanCampagne(envoyes=envoyes, sans_email=sans_email, echecs=echecs)
