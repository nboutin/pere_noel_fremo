from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .database import (
    get_attributions,
    get_confirmed_lutins,
    get_lutin_exclusions,
    get_past_attributions,
)


@dataclass
class AuditResult:
    is_valid: bool
    total_lutins: int
    errors: list[str] = field(default_factory=list)
    # Catégories d'erreurs sans identifiant de Lutin ni paire : affichables en Admin aveugle.
    error_categories: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    attributions_count: int = 0
    # Details accessible to the agent:
    graph_details: dict[str, Any] = field(default_factory=dict)

    @property
    def total_participants(self) -> int:
        """Alias de rétro-compatibilité pour total_lutins."""
        return self.total_lutins


def audit_tirage(db_path: Path | str, year: int) -> AuditResult:
    """Inspecte la validité du graphe d'attribution scellé en base et décèle impasses ou violations.

    Charge les données puis délègue à `audit_pairs`, qui ne fait aucune E/S. Cette fonction offre une
    interface programmatique exploitable par l'agent Antigravity pour diagnostiquer le tirage au sort
    sans divulgation publique.
    """
    confirmed_lutins = get_confirmed_lutins(db_path, year)
    attributions = get_attributions(db_path, year)
    exclusions = {donneur: get_lutin_exclusions(db_path, donneur) for donneur in attributions}
    history = get_past_attributions(db_path, year)
    return audit_pairs(confirmed_lutins, attributions, exclusions, history, year=year)


def audit_pairs(
    confirmed_lutins: dict[str, dict[str, Any]],
    pairs: dict[str, str],
    exclusions: dict[str, list[str]],
    history: dict[str, list[str]],
    *,
    year: int | None = None,
) -> AuditResult:
    """Audit pur (sans E/S) d'un ensemble de paires {donneur: bénéficiaire}.

    `exclusions` et `history` (passé seul, hors édition courante) indexent les listes par donneur.
    `year` n'est utilisé que pour l'affichage.
    Contrôles : impasse de graphe, présence, bijection, auto-cadeau, exclusion et historique.
    """
    attributions = pairs
    errors: list[str] = []
    error_categories: list[str] = []
    warnings: list[str] = []

    def add_error(detail: str, category: str) -> None:
        errors.append(detail)
        error_categories.append(category)

    confirmed_ids = set(confirmed_lutins.keys())
    donneurs = set(attributions.keys())
    beneficiaires = set(attributions.values())

    # 1. Analyse préventive du graphe des candidats (détection d'impasses)
    deadlock_candidates: dict[str, list[str]] = {}
    for lutin_id, params in confirmed_lutins.items():
        excluded = set(params.get("exclude") or [])
        past = set(params.get("history") or [])
        # Candidats potentiels = autres Lutins confirmés qui ne sont ni soi-même, ni exclus, ni dans l'historique
        eligible = [cand for cand in confirmed_ids if cand != lutin_id and cand not in excluded and cand not in past]
        if not eligible:
            add_error(
                f"Impasse de graphe : le Lutin '{lutin_id}' n'a aucun Bénéficiaire admissible "
                "parmi les Lutins confirmés.",
                "Impasse de graphe : un Lutin n'a aucun Bénéficiaire admissible",
            )
        elif len(eligible) == 1:
            warnings.append(
                f"Contrainte critique : le Lutin '{lutin_id}' n'a qu'un seul "
                f"Bénéficiaire admissible possible ('{eligible[0]}')."
            )
        deadlock_candidates[lutin_id] = eligible

    # 2. Vérification de la présence
    if not confirmed_ids:
        add_error(
            f"Aucun Lutin confirmé présent pour l'édition{'' if year is None else f' {year}'}.",
            "Aucun Lutin confirmé présent pour l'édition",
        )

    # Vérification que tous les donneurs sont bien des participants confirmés
    unconfirmed_donneurs = donneurs - confirmed_ids
    if unconfirmed_donneurs:
        add_error(
            f"Donneurs non confirmés présents dans le tirage : {sorted(list(unconfirmed_donneurs))}",
            "Donneurs non confirmés présents dans le tirage",
        )

    unconfirmed_beneficiaires = beneficiaires - confirmed_ids
    if unconfirmed_beneficiaires:
        add_error(
            f"Bénéficiaires non confirmés présents dans le tirage : {sorted(list(unconfirmed_beneficiaires))}",
            "Bénéficiaires non confirmés présents dans le tirage",
        )

    # 3. Vérification de la bijection
    missing_donneurs = confirmed_ids - donneurs
    if missing_donneurs:
        add_error(
            f"Lutins confirmés sans attribution de don : {sorted(list(missing_donneurs))}",
            "Lutins confirmés sans attribution de don",
        )

    missing_beneficiaires = confirmed_ids - beneficiaires
    if missing_beneficiaires:
        add_error(
            f"Lutins confirmés sans attribution de cadeau : {sorted(list(missing_beneficiaires))}",
            "Lutins confirmés sans attribution de cadeau",
        )

    if len(donneurs) != len(beneficiaires):
        add_error(
            f"Non-bijection détectée: {len(donneurs)} donneurs pour {len(beneficiaires)} bénéficiaires distincts.",
            "Non-bijection détectée entre donneurs et bénéficiaires",
        )

    # 4. Vérification des contraintes individuelles sur les attributions scellées
    for donneur_id, beneficiaire_id in attributions.items():
        # Auto-cadeau
        if donneur_id == beneficiaire_id:
            add_error(f"Auto-cadeau détecté pour le Lutin '{donneur_id}'.", "Auto-cadeau détecté")

        # Exclusions
        if beneficiaire_id in exclusions.get(donneur_id, []):
            add_error(
                f"Violation d'exclusion : '{donneur_id}' s'est vu attribuer '{beneficiaire_id}', qui est exclu.",
                "Violation d'exclusion",
            )

        # Historique strict
        if beneficiaire_id in history.get(donneur_id, []):
            add_error(
                f"Violation d'historique : '{donneur_id}' a déjà offert à '{beneficiaire_id}' par le passé.",
                "Violation d'historique",
            )

    is_valid = len(errors) == 0
    return AuditResult(
        is_valid=is_valid,
        total_lutins=len(confirmed_ids),
        attributions_count=len(attributions),
        errors=errors,
        error_categories=error_categories,
        warnings=warnings,
        graph_details={
            "confirmed_count": len(confirmed_ids),
            "attributions_count": len(attributions),
            "donneurs": sorted(list(donneurs)),
            "beneficiaires": sorted(list(beneficiaires)),
            "eligible_targets_per_donneur": deadlock_candidates,
        },
    )
