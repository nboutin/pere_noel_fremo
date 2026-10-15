import argparse
import copy
import sys
from pathlib import Path
from typing import Any, cast

from .annonce import send_annonces
from .config import default_db_path, resolve_res_dir
from .database import import_yaml_data


def create_parser() -> argparse.ArgumentParser:
    res_dir = resolve_res_dir()
    default_db = default_db_path(res_dir)
    default_secure_data = res_dir / "secure_data.yml"

    parser = argparse.ArgumentParser(
        prog="pere-noel",
        description="Le Père Noël de la Frémo - Gestion et tirage au sort",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: init-db
    init_db_parser = subparsers.add_parser(
        "init-db",
        help="Initialise la base SQLite et importe les lutins, exclusions et l'historique",
    )
    init_db_parser.add_argument(
        "--db-path",
        type=Path,
        default=default_db,
        help="Chemin de la base de données SQLite (défaut: res/fremo.db)",
    )
    init_db_parser.add_argument(
        "--year",
        type=int,
        default=2026,
        help="Année de l'édition à initialiser (défaut: 2026)",
    )
    init_db_parser.add_argument(
        "--data-in",
        type=Path,
        default=None,
        help="Chemin du fichier data_in.yml source (défaut: res/{year}/data_in.yml ou res/2025/data_in.yml)",
    )
    init_db_parser.add_argument(
        "--secure-data",
        type=Path,
        default=default_secure_data,
        help="Chemin du fichier secure_data.yml (défaut: res/secure_data.yml)",
    )

    # Subcommand: annonce
    annonce_parser = subparsers.add_parser(
        "annonce",
        help="Envoie l'Annonce avec Lien magique pour confirmer la présence",
    )
    annonce_parser.add_argument(
        "--db-path",
        type=Path,
        default=default_db,
        help="Chemin de la base de données SQLite (défaut: res/fremo.db)",
    )
    annonce_parser.add_argument(
        "--secure-data",
        type=Path,
        default=default_secure_data,
        help="Chemin du fichier secure_data.yml (défaut: res/secure_data.yml)",
    )
    annonce_parser.add_argument(
        "--year",
        type=int,
        default=2026,
        help="Année de l'édition (défaut: 2026)",
    )
    annonce_parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="URL racine pour les Liens magiques (surcharge la configuration)",
    )
    annonce_parser.add_argument(
        "--template",
        type=Path,
        default=None,
        help="Chemin vers le gabarit d'email (défaut: gabarit de l'année ou intégré)",
    )
    annonce_parser.add_argument(
        "--subject",
        type=str,
        default=None,
        help="Objet personnalisé de l'email",
    )
    annonce_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simule l'envoi sans contacter Gmail",
    )
    annonce_parser.add_argument(
        "--no-email",
        action="store_true",
        help="Désactive l'envoi effectif des emails",
    )
    annonce_parser.add_argument(
        "--absent",
        action="append",
        default=[],
        help="Identifiant d'un Lutin absent pour cette édition (peut être répété)",
    )
    annonce_parser.add_argument(
        "--skip",
        action="append",
        default=[],
        help="Alias de compatibilité pour --absent",
    )
    annonce_parser.add_argument(
        "--lutin",
        action="append",
        default=[],
        help="Cible uniquement un identifiant de Lutin spécifique pour un envoi test (peut être répété)",
    )
    annonce_parser.add_argument(
        "--override-email",
        type=str,
        default=None,
        help="Redirige l'envoi de tous les courriels vers cette adresse de test",
    )

    # Subcommand: serve
    serve_parser = subparsers.add_parser(
        "serve",
        help="Démarre le serveur web de l'Espace Lutin",
    )
    serve_parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Adresse d'écoute du serveur web (défaut: 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port d'écoute du serveur web (défaut: 8000)",
    )
    serve_parser.add_argument(
        "--db-path",
        type=Path,
        default=default_db,
        help="Chemin de la base de données SQLite (défaut: res/fremo.db)",
    )

    # Subcommand: tirage
    tirage_parser = subparsers.add_parser(
        "tirage",
        help="Effectue le tirage au sort parmi les Lutins confirmés en mode Admin aveugle",
    )
    tirage_parser.add_argument(
        "--db-path",
        type=Path,
        default=default_db,
        help="Chemin de la base de données SQLite (défaut: res/fremo.db)",
    )
    tirage_parser.add_argument(
        "--year",
        type=int,
        default=2026,
        help="Année de l'édition (défaut: 2026)",
    )
    tirage_parser.add_argument(
        "--organizer",
        type=str,
        default=None,
        help="Identifiant du Lutin organisateur pour préserver son secret",
    )
    tirage_parser.add_argument(
        "--cheater",
        action="append",
        default=[],
        help="Imposer une paire cheater au format 'donneur:beneficiaire' (peut être répété)",
    )
    tirage_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simule le tirage sans enregistrer en base",
    )

    # Subcommand: audit-tirage
    audit_parser = subparsers.add_parser(
        "audit-tirage",
        help="Inspecte la validité du graphe et des contraintes du tirage pour audit agent",
    )
    audit_parser.add_argument(
        "--db-path",
        type=Path,
        default=default_db,
        help="Chemin de la base de données SQLite (défaut: res/fremo.db)",
    )
    audit_parser.add_argument(
        "--year",
        type=int,
        default=2026,
        help="Année de l'édition (défaut: 2026)",
    )

    # Subcommand: revelation
    revelation_parser = subparsers.add_parser(
        "revelation",
        help="Envoie le courriel de Révélation avec Lien magique vers la Carte à gratter",
    )
    revelation_parser.add_argument(
        "--db-path",
        type=Path,
        default=default_db,
        help="Chemin de la base de données SQLite (défaut: res/fremo.db)",
    )
    revelation_parser.add_argument(
        "--secure-data",
        type=Path,
        default=default_secure_data,
        help="Chemin du fichier secure_data.yml (défaut: res/secure_data.yml)",
    )
    revelation_parser.add_argument(
        "--year",
        type=int,
        default=2026,
        help="Année de l'édition (défaut: 2026)",
    )
    revelation_parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="URL racine pour les Liens magiques (surcharge la configuration)",
    )
    revelation_parser.add_argument(
        "--template",
        type=Path,
        default=None,
        help="Chemin vers le gabarit d'email (défaut: gabarit de l'année ou intégré)",
    )
    revelation_parser.add_argument(
        "--subject",
        type=str,
        default=None,
        help="Objet personnalisé de l'email",
    )
    revelation_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simule l'envoi sans contacter Gmail",
    )
    revelation_parser.add_argument(
        "--no-email",
        action="store_true",
        help="Désactive l'envoi effectif des emails",
    )
    revelation_parser.add_argument(
        "--lutin",
        action="append",
        default=[],
        help="Cible uniquement un identifiant de Lutin spécifique pour un envoi test (peut être répété)",
    )
    revelation_parser.add_argument(
        "--override-email",
        type=str,
        default=None,
        help="Redirige l'envoi de tous les courriels vers cette adresse de test",
    )

    # Subcommand: export
    export_parser = subparsers.add_parser(
        "export",
        help="Exporte les attributions et l'historique de l'édition au format YAML d'archive",
    )
    export_parser.add_argument(
        "--db-path",
        type=Path,
        default=default_db,
        help="Chemin de la base de données SQLite (défaut: res/fremo.db)",
    )
    export_parser.add_argument(
        "--year",
        type=int,
        default=2026,
        help="Année de l'édition (défaut: 2026)",
    )
    export_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Chemin du fichier YAML d'export (défaut: res/{year}/data_out.yml)",
    )
    export_parser.add_argument(
        "--data-out",
        type=Path,
        default=None,
        help="Alias de compatibilité pour --output",
    )
    export_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Autorise l'écrasement du fichier d'export s'il existe déjà",
    )

    return parser


def handle_init_db(args: argparse.Namespace) -> int:
    db_path: Path = args.db_path
    data_in_path: Path | None = args.data_in
    secure_data_path: Path = args.secure_data

    if data_in_path is None:
        res_dir = resolve_res_dir()
        candidate_data_in = res_dir / str(args.year) / "data_in.yml"
        default_data_in = res_dir / "2025" / "data_in.yml"
        data_in_path = candidate_data_in if candidate_data_in.exists() else default_data_in

    if not data_in_path.exists():
        print(f"Erreur: Fichier de données introuvable : {data_in_path}")
        return 1

    try:
        counts = import_yaml_data(
            db_path=db_path,
            data_in_path=data_in_path,
            secure_data_path=secure_data_path,
            year=args.year,
        )
        print(
            f"Importation réussie : {counts['lutins']} lutins, "
            f"{counts['exclusions']} exclusions, "
            f"{counts['attributions']} attributions d'historique enregistrées dans {db_path}."
        )
        return 0
    except Exception as exc:
        print(f"Erreur lors de l'importation : {exc}")
        return 1


def handle_annonce(args: argparse.Namespace) -> int:
    db_path: Path = args.db_path
    secure_data_path: Path = args.secure_data

    # Resolve default template path if not provided
    template_path = args.template
    if template_path is None:
        res_dir = resolve_res_dir()
        candidate_template = res_dir / str(args.year) / "annonce.txt"
        if candidate_template.exists():
            template_path = candidate_template
        elif (res_dir / "2025" / "annonce.txt").exists():
            template_path = res_dir / "2025" / "annonce.txt"

    absents_list = list(args.absent or []) + list(args.skip or [])

    try:
        stats = send_annonces(
            db_path=db_path,
            secure_data_path=secure_data_path,
            year=args.year,
            base_url=args.base_url,
            template_path=template_path,
            subject=args.subject,
            dry_run=args.dry_run,
            no_email=args.no_email,
            absents=absents_list,
            target_lutins=list(args.lutin) if args.lutin else None,
            recipient_override=args.override_email,
        )

        if args.dry_run or args.no_email:
            print(
                f"Simulation Annonce : {stats['sent']} courriels préparés (mode simulation), "
                f"{stats['absents']} absents sur {stats['total']} lutins."
            )
            return 0

        echecs = stats.get("echecs", 0)
        print(
            f"Campagne d'Annonce terminée : {stats['sent']} courriels envoyés, "
            f"{echecs} échecs, "
            f"{stats['absents']} absents sur {stats['total']} lutins."
        )
        if echecs > 0:
            print(f"Alerte : {echecs} échec(s) d'envoi détecté(s) lors de la campagne d'Annonce.")
            return 1
        return 0
    except Exception as exc:
        print(f"Erreur lors de la campagne d'Annonce : {exc}")
        return 1


def build_uvicorn_log_config() -> dict[str, Any]:
    """Configure uvicorn's logging dictionary by attaching TokenMaskingFilter to uvicorn.access."""
    import uvicorn.config

    from .web import TokenMaskingFilter

    custom_log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    custom_log_config.setdefault("filters", {})["token_masking"] = {
        "()": TokenMaskingFilter,
    }
    custom_log_config.setdefault("loggers", {}).setdefault("uvicorn.access", {}).setdefault("filters", []).append(
        "token_masking"
    )
    return cast(dict[str, Any], custom_log_config)


def handle_serve(args: argparse.Namespace) -> int:
    import logging

    import uvicorn

    from .web import TokenMaskingFilter, create_app

    custom_log_config = build_uvicorn_log_config()

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.addFilter(TokenMaskingFilter())

    web_app = create_app(db_path=args.db_path)
    print(f"Démarrage de l'Espace Lutin sur http://{args.host}:{args.port} (DB: {args.db_path})")
    uvicorn.run(web_app, host=args.host, port=args.port, log_config=custom_log_config)
    return 0


def handle_tirage(args: argparse.Namespace) -> int:
    from .tirage import run_tirage

    cheaters_list: list[dict[str, str]] = []
    for item in args.cheater or []:
        if ":" in item:
            d, b = item.split(":", 1)
            cheaters_list.append({"donneur": d.strip(), "beneficiaire": b.strip()})

    result = run_tirage(
        db_path=args.db_path,
        year=args.year,
        organizer_id=args.organizer,
        cheaters=cheaters_list if cheaters_list else None,
        dry_run=args.dry_run,
    )
    print(result.get_masked_summary(organizer_id=args.organizer, dry_run=args.dry_run))
    return 0 if result.success else 1


def handle_audit_tirage(args: argparse.Namespace) -> int:
    from .audit import audit_tirage

    audit_result = audit_tirage(db_path=args.db_path, year=args.year)
    status_str = "VALIDE" if audit_result.is_valid else "INVALIDE"
    print(f"=== Audit du tirage ({args.year}) : {status_str} ===")
    print(f"Lutins confirmés : {audit_result.total_lutins}")
    print(f"Attributions enregistrées : {audit_result.attributions_count}")

    if audit_result.errors:
        print("Erreurs détectées :")
        for err in audit_result.errors:
            print(f"  - {err}")

    if audit_result.warnings:
        print("Avertissements :")
        for warn in audit_result.warnings:
            print(f"  - {warn}")

    return 0 if audit_result.is_valid else 1


def handle_revelation(args: argparse.Namespace) -> int:
    from .revelation import send_revelations

    db_path: Path = args.db_path
    secure_data_path: Path = args.secure_data

    # Resolve default template path if not provided
    template_path = args.template
    if template_path is None:
        res_dir = resolve_res_dir()
        candidate_template = res_dir / str(args.year) / "revelation.txt"
        if candidate_template.exists():
            template_path = candidate_template
        elif (res_dir / str(args.year) / "revelation.html").exists():
            template_path = res_dir / str(args.year) / "revelation.html"

    try:
        stats = send_revelations(
            db_path=db_path,
            secure_data_path=secure_data_path,
            year=args.year,
            base_url=args.base_url,
            template_path=template_path,
            subject=args.subject,
            dry_run=args.dry_run,
            no_email=args.no_email,
            target_lutins=list(args.lutin) if args.lutin else None,
            recipient_override=args.override_email,
        )

        if args.dry_run or args.no_email:
            print(
                f"Simulation Révélation : {stats['sent']} courriels préparés (mode simulation) "
                f"pour {stats['total']} lutins confirmés."
            )
            return 0

        echecs = stats.get("echecs", 0)
        print(
            f"Campagne de Révélation terminée : {stats['sent']} courriels envoyés, "
            f"{echecs} échecs sur {stats['total']} lutins confirmés."
        )
        if echecs > 0:
            print(f"Alerte : {echecs} échec(s) d'envoi détecté(s) lors de la campagne de Révélation.")
            return 1
        return 0
    except ValueError as exc:
        print(f"Erreur d'intégrité : {exc}")
        return 1
    except Exception as exc:
        print(f"Erreur lors de la campagne de Révélation : {exc}")
        return 1


def handle_export(args: argparse.Namespace) -> int:
    from .export import export_edition_yaml

    db_path: Path = args.db_path
    year: int = args.year
    output_path = args.output or args.data_out

    if output_path is None:
        res_dir = resolve_res_dir()
        output_path = res_dir / str(year) / "data_out.yml"

    try:
        exported_file = export_edition_yaml(
            db_path=db_path,
            year=year,
            output_path=output_path,
            overwrite=args.overwrite,
        )
        print(f"Exportation d'archive réussie : {exported_file}")
        return 0
    except FileExistsError as exc:
        print(f"Erreur : {exc}")
        return 1
    except Exception as exc:
        print(f"Erreur lors de l'exportation : {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    if argv is None:
        argv = sys.argv[1:]

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    if args.command == "init-db":
        return handle_init_db(args)
    if args.command == "annonce":
        return handle_annonce(args)
    if args.command == "serve":
        return handle_serve(args)
    if args.command == "tirage":
        return handle_tirage(args)
    if args.command == "audit-tirage":
        return handle_audit_tirage(args)
    if args.command == "revelation":
        return handle_revelation(args)
    if args.command == "export":
        return handle_export(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())


def __getattr__(name: str) -> Any:
    if name == "TokenMaskingFilter":
        from .web import TokenMaskingFilter

        return TokenMaskingFilter
    if name == "RES_DIR":
        return resolve_res_dir()
    if name == "DEFAULT_DB_PATH":
        return default_db_path()
    if name == "DEFAULT_DATA_IN":
        return resolve_res_dir() / "2025" / "data_in.yml"
    if name == "DEFAULT_SECURE_DATA":
        return resolve_res_dir() / "secure_data.yml"
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
