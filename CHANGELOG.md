# Changelog

Toutes les modifications notables apportées à ce projet sont documentées dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/)
et ce projet adhère à la spécification [Semantic Versioning](https://semver.org/lang/fr/).

## [Unreleased]

### Added

- Workflow Forgejo Actions `.forgejo/workflows/ci.yml` (verrou, ruff, mypy, bandit, pytest sur Python 3.12 et 3.10, `uv` 0.12.10) et couverture de branches (`--cov-branch`) ; seuil abaissé de 93 % à 92 %, la mesure lignes+branches donnant 92,73 % (#56).

### Changed

- Le tirage audite les paires en mémoire (`audit_pairs`) avant toute écriture, y compris sous `--dry-run` (qui peut donc échouer) ; un audit invalide n'écrit rien et laisse l'état précédent intact. `snapshot_attributions` et `restore_attributions` sont supprimées (#36, #50).
- Catégories d'erreur de l'audit sans identifiant, pour préserver l'Admin aveugle (#36).
- `try_build_gmail_service` partagé par l'Annonce et la Révélation (#36).
- Message explicite pour une grille de Défi invalide au lieu d'une grille vide (#36).
- Les routes de l'Espace Lutin sont désormais synchrones (`def`) et s'exécutent dans le pool de threads de FastAPI au lieu de bloquer la boucle d'événements avec SQLite et la lecture des YAML (#53).
- Grilles : les manches illisibles sont désormais journalisées (WARNING) au lieu d'être ignorées en silence, les noms de jours et de mois en français sont factorisés avec `helper.py` et les rejets du validateur de grille sont couverts par des tests (#51).

### Fixed

- `get_or_assign_pseudo` ne valide plus la transaction de l'appelant : l'attribution du pseudo et la création de la ligne `scores_defi` restent atomiques dans `start_score_defi` (#49).
- `parse_iso_or_legacy` accepte le suffixe `Z` sous Python 3.10, où `datetime.fromisoformat` le refuse.

### Removed

- Alias `get_pseudo_for_lutin` et son re-export dans `defi` (#36).
- Code mort de `database.py` : `start_manche_defi`, `complete_score_defi` (second chemin de complétion qui contournait le plafond d'essais), `get_or_create_score_defi` et `backfill_historical_attributions` avec le module `migrations` (backfill déjà appliqué à `res/fremo.db`, ADR-0008 amendée) (#55).

### Security

- Révélation : nom du Lutin échappé en HTML ; `token.json` écrit en `0600` ; adresses courriel masquées (`a***@domaine`) dans les journaux (#52).

## [2.0.1] - 2026-10-15

### Added
- Commandes `revelation` (notification de Révélation) et `export` (export de clôture YAML) (#14).
- Garde de re-tirage : `pere-noel tirage` refuse une édition `drawn` ou `revealed` sauf drapeau explicite, remplace l'année entière de façon atomique et lance un audit automatique après scellement (#38).
- Option `annonce --interactive-auth` ; sans elle, un jeton Gmail invalide produit un échec explicite (#40).
- Dépendance `tzdata` pour les fuseaux horaires sous Windows et Docker slim (#39).
- Tests des chemins d'erreur de l'audit et de la CLI (#45).

### Changed
- Grilles du Défi pilotées par les catégories de chaque manche : les manches 2, 3, 5, 6, 8, 9, 11, 12, 14 et 15 sont de nouveau jouables ; une manche incohérente est refusée au `start` (#37).
- Heures de déverrouillage interprétées en `Europe/Paris` et dates affichées en français (#39).
- Service Gmail construit une seule fois par campagne d'Annonce, nom du Lutin échappé en HTML (#40).
- Compteur de tentatives de soumission atomique (transactions `BEGIN IMMEDIATE`, délai d'attente SQLite explicite) (#41).
- Build reproductible : bornes sur les dépendances, `uv.lock` suivi et utilisé par le Dockerfile, couverture mesurée avec seuil à 93 % (#42).
- Vocabulaire aligné sur le glossaire : `pseudo_lutin` partout, colonne SQL `pseudo_lugeur` migrée à l'initialisation (#43).
- ADR en double renumérotée : `0010-date-du-repas-de-noel-dans-espace-lutin` devient `0012` (#44).

### Fixed
- Correction du CHANGELOG 2.0.0 : sous-commandes réelles, tirage en Admin aveugle, rendu Canvas (#44).

### Removed
- Clés JSON et alias legacy `pseudo_lugeur`, `generate_pseudo_lugeur` (#43).

## [2.0.0] - 2026-10-14

### Added
- Espace Lutin FastAPI/Starlette avec authentification par Lien magique sans mot de passe.
- Base de données SQLite (`fremo.db`), gestion des tokens et confirmation de présence en ligne.
- CLI d'administration unifiée `pere-noel` (`init-db`, `annonce`, `serve`, `tirage`, `audit-tirage`).
- Tirage en Admin aveugle et Carte à gratter interactive.
- Championnat du Défi du lutin en 15 manches avec grilles de déduction et rendu Canvas anti-OCR dynamique.
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
