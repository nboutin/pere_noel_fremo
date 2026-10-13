from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .database import (
    get_attributions,
    get_confirmed_lutins,
    get_lutin_exclusions,
    get_lutin_history,
)


@dataclass
class AuditResult:
    is_valid: bool
    total_lutins: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    attributions_count: int = 0
    # Details accessible to the agent:
    graph_details: dict[str, Any] = field(default_factory=dict)

    @property
    def total_participants(self) -> int:
        """Alias de rétro-compatibilité pour total_lutins."""
        return self.total_lutins


def audit_tirage(db_path: Path | str, year: int) -> AuditResult:
    """Inspecte la validité du graphe d'attribution et décèle d'éventuelles impasses ou violations.

    Cette fonction offre une interface programmatique exploitable par l'agent Antigravity
    pour diagnostiquer le tirage au sort sans divulgation publique.
    """
    confirmed_lutins = get_confirmed_lutins(db_path, year)
    attributions = get_attributions(db_path, year)

    errors: list[str] = []
    warnings: list[str] = []

    confirmed_ids = set(confirmed_lutins.keys())
    donneurs = set(attributions.keys())
    beneficiaires = set(attributions.values())

    # 1. Analyse préventive du graphe des candidats (détection d'impasses)
    deadlock_candidates: dict[str, list[str]] = {}
    for lutin_id, params in confirmed_lutins.items():
        exclusions = set(params.get("exclude") or [])
        history = set(params.get("history") or [])
        # Candidats potentiels = autres Lutins confirmés qui ne sont ni soi-même, ni exclus, ni dans l'historique
        eligible = [
            cand for cand in confirmed_ids if cand != lutin_id and cand not in exclusions and cand not in history
        ]
        if not eligible:
            errors.append(
                f"Impasse de graphe : le Lutin '{lutin_id}' n'a aucun Bénéficiaire admissible "
                "parmi les Lutins confirmés."
            )
        elif len(eligible) == 1:
            warnings.append(
                f"Contrainte critique : le Lutin '{lutin_id}' n'a qu'un seul "
                f"Bénéficiaire admissible possible ('{eligible[0]}')."
            )
        deadlock_candidates[lutin_id] = eligible

    # 2. Vérification de la présence
    if not confirmed_ids:
        errors.append(f"Aucun Lutin confirmé présent pour l'édition {year}.")

    # Vérification que tous les donneurs sont bien des participants confirmés
    unconfirmed_donneurs = donneurs - confirmed_ids
    if unconfirmed_donneurs:
        errors.append(f"Donneurs non confirmés présents dans le tirage : {sorted(list(unconfirmed_donneurs))}")

    unconfirmed_beneficiaires = beneficiaires - confirmed_ids
    if unconfirmed_beneficiaires:
        errors.append(
            f"Bénéficiaires non confirmés présents dans le tirage : {sorted(list(unconfirmed_beneficiaires))}"
        )

    # 3. Vérification de la bijection
    missing_donneurs = confirmed_ids - donneurs
    if missing_donneurs:
        errors.append(f"Lutins confirmés sans attribution de don : {sorted(list(missing_donneurs))}")

    missing_beneficiaires = confirmed_ids - beneficiaires
    if missing_beneficiaires:
        errors.append(f"Lutins confirmés sans attribution de cadeau : {sorted(list(missing_beneficiaires))}")

    if len(donneurs) != len(beneficiaires):
        errors.append(
            f"Non-bijection détectée: {len(donneurs)} donneurs pour {len(beneficiaires)} bénéficiaires distincts."
        )

    # 4. Vérification des contraintes individuelles sur les attributions scellées
    for donneur_id, beneficiaire_id in attributions.items():
        # Auto-cadeau
        if donneur_id == beneficiaire_id:
            errors.append(f"Auto-cadeau détecté pour le Lutin '{donneur_id}'.")

        # Exclusions
        donneur_exclusions = get_lutin_exclusions(db_path, donneur_id)
        if beneficiaire_id in donneur_exclusions:
            errors.append(
                f"Violation d'exclusion : '{donneur_id}' s'est vu attribuer '{beneficiaire_id}', qui est exclu."
            )

        # Historique strict
        donneur_history = get_lutin_history(db_path, donneur_id)
        matching_count = donneur_history.count(beneficiaire_id)
        if matching_count > 1:
            errors.append(f"Violation d'historique : '{donneur_id}' a déjà offert à '{beneficiaire_id}' par le passé.")

    is_valid = len(errors) == 0
    return AuditResult(
        is_valid=is_valid,
        total_lutins=len(confirmed_ids),
        attributions_count=len(attributions),
        errors=errors,
        warnings=warnings,
        graph_details={
            "year": year,
            "confirmed_count": len(confirmed_ids),
            "attributions_count": len(attributions),
            "donneurs": sorted(list(donneurs)),
            "beneficiaires": sorted(list(beneficiaires)),
            "eligible_targets_per_donneur": deadlock_candidates,
        },
    )
