import html
import logging
from pathlib import Path
from typing import Any

import yaml

from . import helper
from .database import get_confirmed_lutins, get_edition_status, set_edition_status
from .tokens import build_lien_magique_url, create_or_get_token, mark_token_sent

logger = logging.getLogger(__name__)

DEFAULT_REVELATION_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="color-scheme" content="light dark">
    <meta name="supported-color-schemes" content="light dark">
    <title>Le Père Noël de la Frémo - Révélation</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0f172a; \
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" \
style="background-color: #0f172a; padding: 24px 12px;">
        <tr>
            <td align="center">
                <table role="presentation" width="100%" style="max-width: 600px; background-color: #ffffff; \
border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.3);" cellspacing="0" cellpadding="0">
                    <tr>
                        <td bgcolor="#065f46" style="background-color: #065f46; \
background: linear-gradient(135deg, #065f46 0%, #064e3b 100%); padding: 32px 24px; text-align: center; color: #ffffff;">
                            <div style="font-size: 40px; margin-bottom: 8px;">🎁 ✨ 🎄</div>
                            <div style="display: inline-block; background-color: #d97706; color: #ffffff; \
font-size: 12px; font-weight: bold; padding: 4px 12px; border-radius: 9999px; text-transform: uppercase; \
letter-spacing: 1px; margin-bottom: 12px;">Édition {year}</div>
                            <h1 style="margin: 0; font-size: 26px; font-weight: 800; \
letter-spacing: -0.5px; color: #ffffff;">
                                Le Père Noël de la Frémo
                            </h1>
                            <p style="margin: 8px 0 0; font-size: 15px; color: #a7f3d0;">
                                Le Tirage au sort est scellé !
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 32px 28px; line-height: 1.6; font-size: 15px; color: #334155;">
                            <p style="font-size: 18px; font-weight: bold; color: #0f172a; margin-top: 0;">
                                HOHOHO {fullname},
                            </p>
                            <p>
                                Les lutins ont terminé leurs calculs magiques ! Le <strong>Tirage au sort</strong>
                                de l'édition <strong>{year}</strong> a été effectué avec succès
                                dans le plus grand secret.
                            </p>
                            <div style="background-color: #f0fdf4; border-left: 4px solid #10b981; \
border-radius: 6px; padding: 16px; margin: 24px 0;">
                                <h3 style="margin: 0 0 8px; color: #065f46; font-size: 16px;">
                                    ✨ Ta Carte à gratter est disponible !
                                </h3>
                                <p style="margin: 0; font-size: 14px; color: #047857;">
                                    Connecte-toi à ton <strong>Espace Lutin</strong> pour dévoiler l'identité
                                    de ton <strong>Bénéficiaire</strong> sous la Carte à gratter interactive.
                                </p>
                            </div>
                            <p style="font-size: 14px; color: #64748b; margin: 20px 0;">
                                🤫 N'oublie pas : garde le secret absolu jusqu'au <strong>Repas de Noël</strong> !
                                Tu as désormais tout le temps nécessaire pour concocter le cadeau idéal.
                            </p>
                            <table role="presentation" border="0" cellspacing="0" cellpadding="0" align="center" \
style="margin: 36px auto 28px;">
                                <tr>
                                    <td align="center" bgcolor="#059669" style="border-radius: 8px; \
background-color: #059669; background: linear-gradient(135deg, #059669 0%, #047857 100%); \
box-shadow: 0 4px 12px rgba(5, 150, 105, 0.35);">
                                        <a href="{lien_magique}" target="_blank" style="font-size: 16px; \
font-weight: bold; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; \
text-decoration: none; color: #ffffff; padding: 16px 32px; border-radius: 8px; display: inline-block;">
                                            👉 Gratter ma Carte &amp; Découvrir mon Bénéficiaire
                                        </a>
                                    </td>
                                </tr>
                            </table>
                            <p style="text-align: center; font-size: 12px; color: #94a3b8; margin: 0 0 16px;">
                                🔒 <em>Ce lien est magique et strictement personnel (aucun mot de passe requis).
                                Ne le transmets à personne pour préserver la surprise !</em>
                            </p>
                            <p style="font-size: 11px; color: #cbd5e1; word-break: break-all; \
text-align: center; margin-top: 12px;">
                                Si le bouton ne fonctionne pas, copie ce lien dans ton navigateur :<br>
                                <a href="{lien_magique}" style="color: #64748b; text-decoration: underline;">\
{lien_magique}</a>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style="background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 20px 24px; \
text-align: center; font-size: 13px; color: #64748b;">
                            <p style="margin: 0; font-weight: 600; color: #334155;">Le Père Noël de la Frémo 🎅</p>
                            <p style="margin: 4px 0 0; font-size: 12px;">Que la magie de Noël commence !</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""


def format_revelation_body(template: str, fullname: str, lien_magique: str, year: int) -> str:
    """Injecte le nom, l'année et le Lien magique dans le modèle d'email de Révélation."""
    content = (
        template.replace("{fullname}", html.escape(fullname))
        .replace("{lien_magique}", lien_magique)
        .replace("{magic_url}", lien_magique)
        .replace("{year}", str(year))
    )

    if lien_magique not in content:
        cta_html = (
            f'\n<p style="margin-top: 20px;">'
            f'👉 <a href="{lien_magique}" style="font-weight: bold; color: #047857;">'
            f"Accéder à mon Espace Lutin et découvrir mon Bénéficiaire</a>"
            f"</p>\n"
        )
        if "</body>" in content:
            content = content.replace("</body>", f"{cta_html}</body>")
        else:
            content += cta_html

    return content


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
    year: int = 2026,
    base_url: str | None = None,
    template_path: Path | str | None = None,
    subject: str | None = None,
    dry_run: bool = False,
    no_email: bool = False,
    target_lutins: list[str] | None = None,
    recipient_override: str | None = None,
) -> dict[str, int]:
    """Exécute la campagne d'envoi de la Révélation aux Lutins confirmés et passe l'Édition à 'revealed'."""
    # Contrôle d'intégrité : refus strict si l'édition n'est pas 'drawn' ou 'revealed'
    status = get_edition_status(db_path, year)
    if status not in ("drawn", "revealed"):
        raise ValueError(
            f"Impossible d'envoyer la Révélation : l'édition {year} a le statut '{status}', "
            f"elle doit être 'drawn' ou 'revealed'."
        )

    secure_data: dict[str, Any] = {}
    sec_path = Path(secure_data_path)
    if sec_path.exists():
        with open(sec_path, encoding="utf-8") as stream:
            secure_data = yaml.safe_load(stream) or {}

    sender_email = secure_data.get("sender_email", "leperenoeldelafremo@gmail.com")
    effective_base_url = base_url or secure_data.get("base_url") or "http://localhost:8000"
    default_subject = f"🎅 [Père Noël de la Frémo {year}] Le Tirage au sort a eu lieu ! Découvre ton Bénéficiaire"
    email_subject = subject or default_subject

    # Chargement du gabarit de courriel
    template_body: str = DEFAULT_REVELATION_TEMPLATE
    if template_path is not None and Path(template_path).exists():
        with open(template_path, encoding="utf-8") as stream:
            template_body = stream.read()

    confirmed_lutins = get_confirmed_lutins(db_path, year)
    targets_set = set(target_lutins) if target_lutins else None

    # Service Gmail construit une seule fois, hors simulation, en mode non interactif.
    service: Any = None
    service_error: Exception | None = None
    if not (dry_run or no_email):
        service, service_error = helper.try_build_gmail_service("Révélation")

    sent_count = 0
    sans_email_count = 0
    echecs_count = 0

    for lutin_id, params in confirmed_lutins.items():
        if targets_set and lutin_id not in targets_set:
            continue

        token = create_or_get_token(db_path, lutin_id, year)
        lien_magique = build_lien_magique_url(effective_base_url, token)
        body = format_revelation_body(
            template=template_body,
            fullname=params.get("fullname", lutin_id),
            lien_magique=lien_magique,
            year=year,
        )
        text_body = format_revelation_text(
            fullname=params.get("fullname", lutin_id),
            lien_magique=lien_magique,
            year=year,
        )

        to_addr = (
            recipient_override or params.get("email") or secure_data.get("personnes", {}).get(lutin_id, {}).get("email")
        )
        if not to_addr:
            sans_email_count += 1
            logger.warning(f"Lutin confirmé '{lutin_id}' n'a pas d'adresse courriel configurée.")
            continue

        if dry_run or no_email:
            sent_count += 1
            continue

        if service_error is not None:
            echecs_count += 1
            continue

        try:
            helper.gmail_send_email(
                service,
                sender_email=sender_email,
                subject=email_subject,
                body=body,
                toaddr=to_addr,
                text_body=text_body,
            )
            mark_token_sent(db_path, token)
            sent_count += 1
        except helper.EmailSendError as exc:
            echecs_count += 1
            logger.error(
                f"Échec de l'envoi de la Révélation au Lutin '{lutin_id}' ({helper.mask_email(to_addr)}): {exc}"
            )
        except Exception as exc:
            echecs_count += 1
            logger.error(
                f"Erreur inattendue lors de la Révélation au Lutin '{lutin_id}' ({helper.mask_email(to_addr)}): {exc}"
            )

    # Transition du statut de l'édition : 'revealed' sur envoi nominal uniquement
    is_targeted_run = target_lutins is not None and len(target_lutins) > 0
    if not (dry_run or no_email) and not is_targeted_run and echecs_count == 0 and sent_count > 0:
        set_edition_status(db_path, year, "revealed")

    return {
        "total": len(confirmed_lutins),
        "sent": sent_count,
        "sans_email": sans_email_count,
        "echecs": echecs_count,
    }
