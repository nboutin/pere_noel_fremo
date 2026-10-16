# Changelog

Toutes les modifications notables apportées à ce projet sont documentées dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/)
et ce projet adhère à la spécification [Semantic Versioning](https://semver.org/lang/fr/).

## [Unreleased]

## [2.1.1] - 2026-10-16

### Changed

- Réorganisation de l'ordonnancement des cartes de l'Espace Lutin : 1. Confirmation de présence, 2. Bénéficiaire mystère, 3. Statut du championnat, 4. Classement général (tableau défilable d'une hauteur maximale de 400px), 5. Calendrier des manches (avec ancre `#card-defi`), 6. Manche active et Défi du lutin (#76, #77).

## [2.1.0] - 2026-10-16

### Added

- Clôture du Défi du lutin après le Repas de Noël : avec une `date_repas`, le démarrage, la Soumission et l'abandon sont refusés (`DEFI_CLOS`, HTTP 403) dès minuit à Paris le lendemain du Repas, et les manches non terminées s'affichent comme closes (`StatutManche.CLOSE`) ; ADR-0007 amendée. Le compte à rebours du Repas se calcule désormais avec l'horloge de l'application en heure de Paris (#68).
- Journalisation applicative : `main()` appelle `configure_logger("pere_noel.log")` une seule fois pour toutes les sous-commandes ; les messages INFO des modules `pere_noel_fremo.*` sont écrits dans `logs/pere_noel.log`, et le `TokenMaskingFilter` masque les jetons `/lutin/<jeton>` dans les handlers fichier et console. Image Docker inchangée (`/app/logs` appartient déjà à `lutin`) (#70).
- Workflow Forgejo Actions `.forgejo/workflows/ci.yml` (verrou, ruff, mypy, bandit, pytest sur Python 3.12 et 3.10, `uv` 0.12.10) et couverture de branches (`--cov-branch`) ; seuil abaissé de 93 % à 92 %, la mesure lignes+branches donnant 92,73 % (#56).

### Changed

- Revue de code de la spec #65 : `TokenMaskingFilter` et `mask_token_in_text` migrent de `web` vers `helper` (plus d'import différé de `web` dans `configure_logger`) ; `_refus_parcours` porte toute la traduction statut vers HTTP (indices compris, codes et messages inchangés) ; `database._confirmed_rows` est l'unique requête des Lutins confirmés et `get_edition_date_repas` (qui accepte une connexion) l'unique lecteur de `editions.date_repas` ; `PARIS_TZ` vit dans `config`. Un `--override-email` vide reste un envoi redirigé, et l'Annonce, comme la Révélation, n'avance l'Édition qu'après un envoi nominal sans aucun échec (`BilanCampagne.fait_avancer_edition`) ; le glossaire définit envoi nominal, ciblé, redirigé et Défi clos.
- `campagne.rendre_gabarit` et la dataclass figée `Cta` : le rendu du gabarit HTML (échappement du nom, marqueurs, CTA avant `</body>`) n'existe plus qu'à un endroit ; `format_annonce_body` et `format_revelation_body` en sont de minces appels, signatures inchangées (#72).
- Nouveau module `presence` (`confirmer`) : la garde d'Édition scellée et l'écriture de la présence s'exécutent dans une seule transaction `BEGIN IMMEDIATE` ; `save_attributions` relit les Lutins confirmés dans sa transaction et lève `PresencesChangees` (rollback, Édition non scellée) si les donneurs diffèrent, ce que `run_tirage` traduit en échec « les présences ont changé, relancez le tirage » sans identifiant. Codes et messages HTTP de la route présence inchangés (#67).
- `parcours.indices` : les routes `/defi/indices` et `/defi/{id}/indices` passent par le module Parcours (mêmes gardes que les autres routes, dont la clôture `DEFI_CLOS`) ; `_get_lutin_and_manche_or_raise` et la garde HTTP dupliquée sont supprimées, codes et messages inchangés (#73).
- `--force-retirage` sur une Édition déjà `revealed` est désormais refusé (transition `revealed` -> `drawn` interdite : une Édition close ne se rouvre pas) (#57).
- Nouveau module `campagne` : une seule boucle d'envoi (`envoyer_campagne`) pour l'Annonce et la Révélation, derrière le port `Expediteur` (adaptateurs `ExpediteurGmail` et `ExpediteurMemoire`) ; `send_annonces` et `send_revelations` deviennent de minces configurations (signatures et sortie de la CLI inchangées, paramètre optionnel `expediteur` ajouté), le repli sur l'adresse de `secure_data` s'applique aux deux, et les gabarits par défaut migrent vers `gabarits.py` (#63).
- `parcours.etat` : le statut d'une manche (`resolue`, `abandonnee`, `scellee`, `disponible`, `en_cours`, `verrouillee`) est dérivé du Parcours en une seule requête pour toutes les manches d'un Lutin ; le barème (1 pt pour `scellee`, 0 pt pour `abandonnee`, ADR-0007 inchangé) s'appuie sur ce statut au lieu d'un seuil sur `attempts`, et l'Espace Lutin n'a plus de `status_tag` ni de boucle `get_score_defi` (`scellee` s'affiche comme `abandonnee`) (#60).
- Nouveau module `edition` : unique propriétaire du statut d'une Édition (`statut`, `avancer`, `est_scellee`, `annee_courante`), l'Annonce fait passer l'Édition de `draft` à `announced` après le premier envoi réussi, et les années `2026` codées en dur de la CLI, de l'Annonce et de la Révélation sont remplacées par l'Édition la plus récente (#61).
- Le tirage audite les paires en mémoire (`audit_pairs`) avant toute écriture, y compris sous `--dry-run` (qui peut donc échouer) ; un audit invalide n'écrit rien et laisse l'état précédent intact. `snapshot_attributions` et `restore_attributions` sont supprimées (#36, #50).
- Catégories d'erreur de l'audit sans identifiant, pour préserver l'Admin aveugle (#36).
- `try_build_gmail_service` partagé par l'Annonce et la Révélation (#36).
- Message explicite pour une grille de Défi invalide au lieu d'une grille vide (#36).
- Nouveau module `parcours` (`demarrer`, `abandonner`) : présence, déverrouillage, validité de la grille, pseudo et écriture de `scores_defi` s'enchaînent dans une seule transaction ; les routes start et abandon de l'Espace Lutin ne portent plus aucune garde et traduisent le résultat en code HTTP, sans changement de codes ni de messages (#58).
- `parcours.soumettre` internalise la Soumission : complétude, validation, plafond d'essais, pénalité et scellement s'enchaînent dans une seule transaction, avec les seules constantes de `defi.py` ; `register_solve_attempt` est supprimée et la route solve ne fait plus que traduire le `ResultatSoumission`, sans changement de réponse JSON (#59).
- Les routes de l'Espace Lutin sont désormais synchrones (`def`) et s'exécutent dans le pool de threads de FastAPI au lieu de bloquer la boucle d'événements avec SQLite et la lecture des YAML (#53).
- Grilles : les manches illisibles sont désormais journalisées (WARNING) au lieu d'être ignorées en silence, les noms de jours et de mois en français sont factorisés avec `helper.py` et les rejets du validateur de grille sont couverts par des tests (#51).

### Fixed

- Grilles : un `manche_N.yml` illisible (YAML invalide, erreur d'E/S ou contenu non dict) est traité comme une manche introuvable (404 « Manche N introuvable » sur start, solve, abandon et indices, au lieu de 500) avec un WARNING sans traceback ; la lecture passe par un lecteur unique `defi._lire_manche` partagé par `get_manche` et `get_all_manches` (#71).
- Un envoi redirigé (`--override-email`) n'a plus aucun effet d'état (ni `sent_at`, ni transition d'Édition) et un envoi ciblé (`--lutin`) ne fait plus avancer l'Édition : seul un envoi nominal (ni redirigé, ni ciblé) le fait, règle portée par `campagne` via `BilanCampagne.nominal` (#66).
- Préparation d'Édition : `init-db` n'a plus de repli sur `res/2025/data_in.yml` (code 1 et chemin attendu nommé si le fichier de l'année manque) et `annonce` utilise le gabarit intégré, en l'indiquant, au lieu du gabarit 2025 ; l'import désactive désormais les Lutins actifs absents de `data_in.yml` (attributions et historique conservés) et `init-db` affiche leur nombre (#69).
- Une Édition future n'influence plus le tirage ni l'audit : l'Historique est unique (`historique_avant`, millésimes strictement antérieurs), chargé en une requête et partagé par le tirage, l'audit et l'export (#62).
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
