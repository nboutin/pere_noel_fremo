import copy
import logging
from dataclasses import dataclass, field
from pathlib import Path
from random import randint
from typing import Any

from .audit import audit_tirage
from .database import (
    get_confirmed_lutins,
    get_edition_status,
    save_attributions,
)

logger = logging.getLogger(__name__)

DEFAULT_CHEATERS: list[dict[str, str]] = []


@dataclass
class TirageResult:
    success: bool
    year: int
    attributions: dict[str, str] = field(default_factory=dict)
    confirmed_count: int = 0
    attempts: int = 0
    message: str = ""

    def get_masked_summary(self, organizer_id: str | None = None, dry_run: bool = False) -> str:
        """Génère un résumé textuel masquant les attributions de l'organisateur et des Lutins.

        Préserve l'anonymat complet en mode Admin aveugle.
        """
        lines = [
            f"=== Tirage au sort de l'édition {self.year} ===",
            f"Statut : {'SUCCÈS' if self.success else 'ÉCHEC'}",
            f"Nombre de Lutins confirmés présents : {self.confirmed_count}",
            f"Attributions calculées : {len(self.attributions)}",
            "",
            "--- Résumé Console (Mode Admin Aveugle) ---",
        ]
        if organizer_id:
            lines.append(f"Organisateur détecté : {organizer_id}")
            lines.append(f"Donneur de {organizer_id} : *** SECRET ***")
            lines.append(f"Bénéficiaire de {organizer_id} : *** SECRET ***")

        if dry_run:
            lines.extend(
                [
                    "Détail des correspondances : *** SECRET ***",
                    "[SIMULATION] Aucune attribution n'a été scellée en base SQLite (--dry-run).",
                ]
            )
        else:
            lines.extend(
                [
                    "Détail des correspondances : *** SECRET ***",
                    "Toutes les paires ont été scellées de manière sécurisée en base SQLite.",
                    "Consultez l'audit programmatique pour toute vérification d'intégrité.",
                ]
            )
        return "\n".join(lines)


def solve_tirage(
    data: dict[str, Any],
    cheaters: list[dict[str, str]] | None = None,
) -> dict[str, str] | None:
    """Résout le problème de bijection du Père Noël avec contraintes d'exclusion et d'historique.

    Retourne un dictionnaire {donneur: beneficiaire} ou None si aucune solution trouvée.
    """
    if not data:
        return None

    cheaters_list = cheaters if cheaters is not None else DEFAULT_CHEATERS
    data_working = copy.deepcopy(data)

    MAX_ATTEMPTS = 500
    MAX_STEPS_PER_ATTEMPT = 2000
    target_count = len(data_working)

    lutins_list = list(data_working.keys())

    # Filtrer les cheaters dont le donneur et le bénéficiaire sont tous deux présents
    # Compatible avec {"giver": ..., "gifted": ...} et {"donneur": ..., "beneficiaire": ...}
    active_cheaters: list[tuple[str, str]] = []
    for ch in cheaters_list:
        d = ch.get("donneur") or ch.get("giver")
        b = ch.get("beneficiaire") or ch.get("gifted")
        if d and b and d in data_working and b in data_working:
            active_cheaters.append((d, b))

    for _attempt in range(1, MAX_ATTEMPTS + 1):
        donneurs_faits: list[str] = []
        beneficiaires_choisis: list[str] = []
        paires: dict[str, str] = {}
        steps = 0

        # Initialiser avec les associations forcées (cheaters)
        for donneur, beneficiaire in active_cheaters:
            if donneur not in donneurs_faits and beneficiaire not in beneficiaires_choisis:
                donneurs_faits.append(donneur)
                beneficiaires_choisis.append(beneficiaire)
                paires[donneur] = beneficiaire

        while len(donneurs_faits) < target_count and steps < MAX_STEPS_PER_ATTEMPT:
            steps += 1
            idx_donneur = randint(0, len(lutins_list) - 1)
            idx_beneficiaire = randint(0, len(lutins_list) - 1)

            donneur = lutins_list[idx_donneur]
            beneficiaire = lutins_list[idx_beneficiaire]

            if donneur == beneficiaire:  # auto-cadeau interdit
                continue

            if donneur in donneurs_faits:
                continue

            if beneficiaire in beneficiaires_choisis:
                continue

            if beneficiaire not in data_working:
                continue

            if beneficiaire in data_working[donneur].get("exclude", []):
                continue

            if beneficiaire in data_working[donneur].get("history", []):
                continue

            donneurs_faits.append(donneur)
            beneficiaires_choisis.append(beneficiaire)
            paires[donneur] = beneficiaire

        if len(donneurs_faits) == target_count:
            return paires

    return None


def run_tirage(
    db_path: Path | str,
    year: int,
    organizer_id: str | None = None,
    cheaters: list[dict[str, str]] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> TirageResult:
    """Extrait les Lutins confirmés présents, applique le solveur, scelle en SQLite et retourne le résultat.

    Le tirage est une transition d'état gardée : sur une édition `drawn` ou `revealed`, il est refusé
    (sans écriture) sauf si `force` est vrai. Après scellement, un audit est lancé automatiquement.
    """
    status = get_edition_status(db_path, year)
    if status in ("drawn", "revealed") and not force and not dry_run:
        return TirageResult(
            success=False,
            year=year,
            message=(
                f"L'édition {year} est déjà au statut '{status}' : un nouveau tirage changerait les "
                "Bénéficiaires déjà consultables. Utilisez --force-retirage pour le forcer explicitement."
            ),
        )

    confirmed_lutins = get_confirmed_lutins(db_path, year)
    confirmed_count = len(confirmed_lutins)

    if confirmed_count < 2:
        return TirageResult(
            success=False,
            year=year,
            confirmed_count=confirmed_count,
            message=f"Nombre insuffisant de Lutins confirmés présents ({confirmed_count}) pour effectuer un tirage.",
        )

    # Solveur
    pairs = solve_tirage(confirmed_lutins, cheaters=cheaters)
    if pairs is None:
        return TirageResult(
            success=False,
            year=year,
            confirmed_count=confirmed_count,
            message="Impossible de trouver une combinaison valide satisfaisant toutes les contraintes.",
        )

    if not dry_run:
        save_attributions(db_path, year, pairs)
        audit = audit_tirage(db_path, year)
        if not audit.is_valid:
            logger.error(f"Audit du tirage {year} invalide ({len(audit.errors)} erreur(s)).")
            return TirageResult(
                success=False,
                year=year,
                confirmed_count=confirmed_count,
                # Les erreurs détaillées nomment des paires : on n'expose que leur nombre (Admin aveugle).
                message=(
                    f"Audit du tirage invalide ({len(audit.errors)} erreur(s) détectée(s)). "
                    "Les détails ne sont pas affichés pour préserver l'Admin aveugle."
                ),
            )

    # En mode admin aveugle, logger les informations d'exécution sans divulguer les paires
    logger.info(
        f"Tirage au sort {year} réalisé avec succès pour {confirmed_count} Lutins confirmés (Mode Admin Aveugle)."
    )

    return TirageResult(
        success=True,
        year=year,
        attributions=pairs,
        confirmed_count=confirmed_count,
        message="Tirage effectué et scellé avec succès.",
    )
