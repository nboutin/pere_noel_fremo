import logging
from pathlib import Path
from typing import Any

import yaml

from . import helper
from .database import get_lutins
from .tokens import build_lien_magique_url, create_or_get_token, mark_token_sent

logger = logging.getLogger(__name__)

DEFAULT_ANNONCE_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Annonce du Père Noël de la Frémo</title>
</head>
<body>
    <p><strong>HOHOHO {fullname},</strong></p>
    <p>Le Père Noël de la Frémo lance officiellement l'édition {year} !</p>
    <p>Rends-toi sur ton Espace Lutin sécurisé pour confirmer ta présence :</p>
    <p style="margin-top: 20px;">
        👉 <a href="{lien_magique}" style="font-weight: bold; color: #b30000;">Accéder à mon Espace Lutin</a>
    </p>
    <p><em>Le Père Noël de la Frémo</em> 🎅</p>
</body>
</html>
"""


def format_annonce_body(template: str, fullname: str, magic_url: str, year: int) -> str:
    """Injecte le nom, l'année et le Lien magique dans le modèle d'email d'Annonce."""
    content = (
        template.replace("{fullname}", fullname)
        .replace("{lien_magique}", magic_url)
        .replace("{magic_url}", magic_url)
        .replace("{year}", str(year))
    )

    # Si le modèle ne contenait aucun marqueur de Lien magique, on l'ajoute automatiquement
    if magic_url not in content:
        cta_html = (
            f'\n<p style="margin-top: 20px;">'
            f'👉 <a href="{magic_url}" style="font-weight: bold; color: #b30000;">Accéder à mon Espace Lutin</a>'
            f"</p>\n"
        )
        if "</body>" in content:
            content = content.replace("</body>", f"{cta_html}</body>")
        else:
            content += cta_html

    return content


def send_annonces(
    db_path: Path | str,
    secure_data_path: Path | str,
    year: int = 2026,
    base_url: str | None = None,
    template_path: Path | str | None = None,
    subject: str | None = None,
    dry_run: bool = False,
    no_email: bool = False,
    absents: list[str] | None = None,
    skip: list[str] | None = None,
) -> dict[str, int]:
    """Exécute la campagne d'envoi de l'Annonce aux Lutins actifs et consigne l'état d'envoi en base."""
    secure_data: dict[str, Any] = {}
    sec_path = Path(secure_data_path)
    if sec_path.exists():
        with open(sec_path, encoding="utf-8") as stream:
            secure_data = yaml.safe_load(stream) or {}

    sender_email = secure_data.get("sender_email", "leperenoeldelafremo@gmail.com")
    effective_base_url = base_url or secure_data.get("base_url") or "http://localhost:8000"
    email_subject = subject or f"[{year}] Le Père Noël de la Frémo : Lancement officiel et Annonce"

    # Chargement du gabarit de courriel
    template_body: str = DEFAULT_ANNONCE_TEMPLATE
    if template_path is not None and Path(template_path).exists():
        with open(template_path, encoding="utf-8") as stream:
            template_body = stream.read()

    # Gestion des absents (terme canonique, avec fallback de compatibilité skip)
    absents_set = set(absents or [])
    if skip:
        absents_set.update(skip)

    lutins = get_lutins(db_path, active_only=True)

    sent_count = 0
    absent_count = 0
    sans_email_count = 0

    for lutin_id, params in lutins.items():
        if lutin_id in absents_set:
            absent_count += 1
            continue

        token = create_or_get_token(db_path, lutin_id, year)
        magic_url = build_lien_magique_url(effective_base_url, token)
        body = format_annonce_body(
            template=template_body,
            fullname=params.get("fullname", lutin_id),
            magic_url=magic_url,
            year=year,
        )

        to_addr = params.get("email")
        if not to_addr:
            sans_email_count += 1
            logger.warning(f"Lutin '{lutin_id}' n'a pas d'adresse courriel configurée.")
            continue

        if dry_run or no_email:
            sent_count += 1
            continue

        try:
            helper.gmail_send_email(
                sender_email=sender_email,
                subject=email_subject,
                body=body,
                toaddr=to_addr,
            )
            mark_token_sent(db_path, token)
            sent_count += 1
        except Exception as exc:
            logger.error(f"Échec de l'envoi du courriel à {to_addr} pour '{lutin_id}': {exc}")

    return {
        "total": len(lutins),
        "sent": sent_count,
        "absents": absent_count,
        "sans_email": sans_email_count,
    }
