import argparse
import sys
from pathlib import Path

from .annonce import send_annonces
from .database import import_yaml_data

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RES_DIR = PROJECT_ROOT / "res"
DEFAULT_DB_PATH = RES_DIR / "fremo.db"
DEFAULT_DATA_IN = RES_DIR / "2025" / "data_in.yml"
DEFAULT_SECURE_DATA = RES_DIR / "secure_data.yml"


def create_parser() -> argparse.ArgumentParser:
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
        default=DEFAULT_DB_PATH,
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
        default=DEFAULT_DATA_IN,
        help="Chemin du fichier data_in.yml source (défaut: res/2025/data_in.yml)",
    )
    init_db_parser.add_argument(
        "--secure-data",
        type=Path,
        default=DEFAULT_SECURE_DATA,
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
        default=DEFAULT_DB_PATH,
        help="Chemin de la base de données SQLite (défaut: res/fremo.db)",
    )
    annonce_parser.add_argument(
        "--secure-data",
        type=Path,
        default=DEFAULT_SECURE_DATA,
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

    return parser


def handle_init_db(args: argparse.Namespace) -> int:
    db_path: Path = args.db_path
    data_in_path: Path = args.data_in
    secure_data_path: Path = args.secure_data

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
        candidate_template = RES_DIR / str(args.year) / "annonce.txt"
        if candidate_template.exists():
            template_path = candidate_template
        elif (RES_DIR / "2025" / "annonce.txt").exists():
            template_path = RES_DIR / "2025" / "annonce.txt"

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
        )

        if args.dry_run or args.no_email:
            print(
                f"Simulation Annonce : {stats['sent']} courriels préparés (mode simulation), "
                f"{stats['absents']} absents sur {stats['total']} lutins."
            )
        else:
            print(
                f"Campagne d'Annonce terminée : {stats['sent']} courriels envoyés, "
                f"{stats['absents']} absents sur {stats['total']} lutins."
            )
        return 0
    except Exception as exc:
        print(f"Erreur lors de la campagne d'Annonce : {exc}")
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
