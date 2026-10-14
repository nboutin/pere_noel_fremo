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
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="color-scheme" content="light dark">
    <meta name="supported-color-schemes" content="light dark">
    <title>Le Père Noël de la Frémo - Annonce</title>
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
                        <td bgcolor="#991b1b" style="background-color: #991b1b; \
background: linear-gradient(135deg, #991b1b 0%, #7f1d1d 100%); padding: 32px 24px; text-align: center; color: #ffffff;">
                            <div style="font-size: 40px; margin-bottom: 8px;">🎅 ❄️ 🎄</div>
                            <div style="display: inline-block; background-color: #d97706; color: #ffffff; \
font-size: 12px; font-weight: bold; padding: 4px 12px; border-radius: 9999px; text-transform: uppercase; \
letter-spacing: 1px; margin-bottom: 12px;">Édition {year}</div>
                            <h1 style="margin: 0; font-size: 26px; font-weight: 800; \
letter-spacing: -0.5px; color: #ffffff;">
                                Le Père Noël de la Frémo
                            </h1>
                            <p style="margin: 8px 0 0; font-size: 15px; color: #fecaca;">
                                L'atelier du Pôle Nord ouvre officiellement ses portes !
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 32px 28px; line-height: 1.6; font-size: 15px; color: #334155;">
                            <p style="font-size: 18px; font-weight: bold; color: #0f172a; margin-top: 0;">
                                HOHOHO {fullname},
                            </p>
                            <p>
                                Les premiers flocons tombent sur la Frémo et l'effervescence gagne le Pôle Nord.
                                Pour cette édition <strong>{year}</strong>, nous inaugurons une toute nouvelle
                                tradition : ton <strong>Espace Lutin</strong> personnel et interactif !
                            </p>
                            <div style="background-color: #fef2f2; border-left: 4px solid #ef4444; \
border-radius: 6px; padding: 16px; margin: 24px 0;">
                                <h3 style="margin: 0 0 8px; color: #991b1b; font-size: 16px;">
                                    📌 1. Confirme ta présence
                                </h3>
                                <p style="margin: 0; font-size: 14px; color: #7f1d1d;">
                                    Pour que le traîneau soit équilibré, la participation au tirage au sort doit être
                                    confirmée avant le <strong>dimanche 1er novembre {year} à 23h59</strong>.
                                    Un simple clic sur ton Espace Lutin suffit pour valider ou décliner.
                                </p>
                            </div>
                            <div style="background-color: #fefce8; border-left: 4px solid #eab308; \
border-radius: 6px; padding: 16px; margin: 24px 0;">
                                <h3 style="margin: 0 0 8px; color: #854d0e; font-size: 16px;">
                                    🧩 2. Le Défi du lutin : Manche 1 déjà ouverte !
                                </h3>
                                <p style="margin: 0; font-size: 14px; color: #713f12;">
                                    Le grand championnat des lutins est lancé ! Résous les grilles logiques au fil
                                    des semaines pour marquer des points au classement.
                                    <strong>Rappel du trophée suprême :</strong> le Lutin qui remportera le championnat
                                    aura le privilège d'ouvrir son cadeau en premier lors de la fête !
                                </p>
                            </div>
                            <p style="font-size: 14px; color: #64748b; margin: 20px 0;">
                                🎁 <em>Et le cadeau secret ?</em> Dès la clôture des confirmations de présence,
                                le <strong>Tirage au sort</strong> sera effectué et une <strong>Carte à gratter</strong>
                                virtuelle se débloquera sur ton Espace Lutin pour révéler ton Bénéficiaire.
                            </p>
                            <table role="presentation" border="0" cellspacing="0" cellpadding="0" align="center" \
style="margin: 36px auto 28px;">
                                <tr>
                                    <td align="center" bgcolor="#dc2626" style="border-radius: 8px; \
background-color: #dc2626; background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%); \
box-shadow: 0 4px 12px rgba(220, 38, 38, 0.35);">
                                        <a href="{lien_magique}" target="_blank" style="font-size: 16px; \
font-weight: bold; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; \
text-decoration: none; color: #ffffff; padding: 16px 32px; border-radius: 8px; display: inline-block;">
                                            👉 Accéder à mon Espace Lutin
                                        </a>
                                    </td>
                                </tr>
                            </table>
                            <p style="text-align: center; font-size: 12px; color: #94a3b8; margin: 0 0 16px;">
                                🔒 <em>Ce lien est magique et strictement personnel (aucun mot de passe requis).
                                Ne le transmets pas pour garder tes secrets de Lutin bien au chaud !</em>
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
                            <p style="margin: 4px 0 0; font-size: 12px;">\
Rendez-vous sur l'Espace Lutin pour préparer les festivités !</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
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
    target_lutins: list[str] | None = None,
    recipient_override: str | None = None,
) -> dict[str, int]:
    """Exécute la campagne d'envoi de l'Annonce aux Lutins actifs et consigne l'état d'envoi en base."""
    secure_data: dict[str, Any] = {}
    sec_path = Path(secure_data_path)
    if sec_path.exists():
        with open(sec_path, encoding="utf-8") as stream:
            secure_data = yaml.safe_load(stream) or {}

    sender_email = secure_data.get("sender_email", "leperenoeldelafremo@gmail.com")
    effective_base_url = base_url or secure_data.get("base_url") or "http://localhost:8000"
    email_subject = subject or f"🎅 [Père Noël de la Frémo {year}] Ton Espace Lutin est ouvert !"

    # Chargement du gabarit de courriel
    template_body: str = DEFAULT_ANNONCE_TEMPLATE
    if template_path is not None and Path(template_path).exists():
        with open(template_path, encoding="utf-8") as stream:
            template_body = stream.read()

    # Gestion des absents (terme canonique, avec fallback de compatibilité skip)
    absents_set = set(absents or [])
    if skip:
        absents_set.update(skip)

    targets_set = set(target_lutins) if target_lutins else None

    lutins = get_lutins(db_path, active_only=True)

    sent_count = 0
    absent_count = 0
    sans_email_count = 0

    for lutin_id, params in lutins.items():
        if targets_set and lutin_id not in targets_set:
            continue
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

        to_addr = recipient_override or params.get("email")
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
