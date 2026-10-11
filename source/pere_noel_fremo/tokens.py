import secrets
from pathlib import Path
from typing import Any

from .database import get_db_connection


def generate_magic_token() -> str:
    """Génère un jeton cryptographiquement sécurisé et utilisable en URL pour le Lien magique."""
    return secrets.token_urlsafe(16)


def build_lien_magique_url(base_url: str, token: str) -> str:
    """Construit l'URL complète du Lien magique à partir de l'URL racine et du jeton."""
    return f"{base_url.rstrip('/')}/lutin/{token}"


# Alias de compatibilité
build_magic_url = build_lien_magique_url


def create_or_get_token(db_path: Path | str, lutin_id: str, year: int) -> str:
    """Génère ou récupère de manière idempotente le jeton de Lien magique d'un Lutin pour une édition."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            # S'assurer que l'édition existe
            conn.execute(
                "INSERT OR IGNORE INTO editions (year, status) VALUES (?, 'draft');",
                (year,),
            )
            # Vérifier si un jeton existe déjà
            existing = conn.execute(
                "SELECT token FROM tokens WHERE lutin_id = ? AND year = ?;",
                (lutin_id, year),
            ).fetchone()
            if existing:
                return str(existing["token"])

            new_token = generate_magic_token()
            conn.execute(
                "INSERT INTO tokens (token, lutin_id, year) VALUES (?, ?, ?);",
                (new_token, lutin_id, year),
            )
            return new_token
    finally:
        conn.close()


def mark_token_sent(db_path: Path | str, token: str) -> None:
    """Consigne l'horodatage d'envoi du courriel pour un jeton de Lien magique."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE tokens SET sent_at = CURRENT_TIMESTAMP WHERE token = ?;",
                (token,),
            )
    finally:
        conn.close()


def get_lutin_by_token(db_path: Path | str, token: str) -> dict[str, Any] | None:
    """Résout un Lutin et son édition associée à partir de son jeton de Lien magique."""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT l.id, l.fullname, l.email, l.is_active, t.token, t.year, t.sent_at
            FROM tokens t
            JOIN lutins l ON t.lutin_id = l.id
            WHERE t.token = ?;
            """,
            (token,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "fullname": row["fullname"],
            "email": row["email"],
            "is_active": bool(row["is_active"]),
            "token": row["token"],
            "year": row["year"],
            "sent_at": row["sent_at"],
        }
    finally:
        conn.close()
