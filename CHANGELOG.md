# Changelog

Toutes les modifications notables apportées à ce projet sont documentées dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/)
et ce projet adhère à la spécification [Semantic Versioning](https://semver.org/lang/fr/).

## [2.0.0] - 2026-10-14

### Added
- Espace Lutin FastAPI/Starlette avec authentification par Lien magique sans mot de passe.
- Base de données SQLite (`fremo.db`), gestion des tokens et confirmation de présence en ligne.
- CLI d'administration unifiée `pere-noel` (`tirage`, `annonce`, `serve`, `stats`, `defi`, `lutin`, `backfill`).
- Tirage aveugle cryptographique et Carte à gratter interactive.
- Championnat du Défi du lutin en 15 manches avec grilles de déduction et rendu SVG anti-OCR dynamique.
- Conteneurisation Docker, stack Dockge et exposition sécurisée Tailscale Funnel.
- Attributions de pseudo de lutin persistées et tirées aléatoirement sans remise (#26).
- Chronométrage précis à la milliseconde en UTC avec horloge injectable (#33).
- Compteur de soumissions (3 essais max par manche), pénalités de temps (15s par échec) et scellement d'abandon avec point de participation (#29).
- Distribution des indices conditionnée au démarrage effectif de la manche et endpoint de reprise (#25).
- Alternative texte pour les e-mails d'annonce avec Lien magique (#27).
- Module de configuration centralisée `config.py` et factory `create_app` (#28).
- Filtrage et masquage des jetons dans les journaux d'accès HTTP (#32).

### Changed
- Remontée explicite des erreurs d'envoi Gmail et comptage des échecs (#27).
- Exécution du conteneur sous utilisateur non privilégié `lutin` (UID 1000) et liaison loopback `127.0.0.1:8000` (#32).
- `backfill_historical_attributions` rendu strictement non-destructif par défaut (#30).
- Dépendances de développement centralisées dans `pyproject.toml` sous `[project.optional-dependencies]` (#31).

### Removed
- Retrait des points d'entrée CLI legacy `pere-noel-tossing` et `pere-noel-annonce` (#30).

## [1.5.0] - 2026-10-11

### Added
- Arguments CLI officiels `--year`, `--skip`, `--dry-run` et `--no-email` pour `pere-noel-tossing` et `pere-noel-annonce`.
- Fonction de validation préalable `validate_lutins_data()` pour vérifier l'intégrité et la structure de `data_in.yml`.
- Suite de tests de non-régression avec `pytest` (`tests/test_tossing.py` et `tests/test_helper.py`) couvrant les invariants du tirage, les parsers CLI et la structure MIME des e-mails.
- Redirection et isolation des fichiers de journaux d'exécution dans le sous-dossier `logs/`.
- ADRs 0001 à 0004 formalisant les choix d'outillage, de qualité, de structure de package et de résilience du tirage.
- Glossaire métier formalisé dans `GLOSSARY.md`.

### Changed
- Restructuration du code applicatif en layout standard sous `source/pere_noel_fremo/`.
- Remplacement de flake8 et pylint par Ruff (linter et formatter).
- Algorithme de tirage au sort multi-tentatives (`MAX_ATTEMPTS`) pour prévenir les impasses partielles.
- Cast explicite des identifiants d'authentification (`Credentials`) pour la compatibilité Mypy sous `warn_return_any = true`.

### Fixed
- Détection d'impasses et bouclage infini lors de tirages avec fortes contraintes d'exclusion ou d'historique.
- Isolation stricte des tokens et données sensibles dans `.gitignore` (`logs/`, `**/secure_data.yml`).

## [1.0.0] - 2022-10-17

### Added
- Version initiale du tirage au sort et de l'envoi d'e-mails pour le Père Noël secret de la Frémo via l'API Gmail.
- Gestion des exclusions et de l'historique permanent des attributions.
