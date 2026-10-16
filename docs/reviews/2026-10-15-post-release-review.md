# Project Review: Le Père Noël de la Frémo (Post-release 2.0.1)

**Date:** 2026-10-15
**Commit:** ab916b3 (arbre de travail propre)
**Stack Profile:** Python (3.10+, FastAPI + SQLite)
**Reviewer:** AI Pair Programmer

## Executive Summary

Cette revue suit celle du matin ([2026-10-15-project-review.md](2026-10-15-project-review.md)) et porte sur la version 2.0.1 et le correctif `ab916b3`. Les constats bloquants et majeurs de la revue précédente sont corrigés. Les 15 grilles de 2026 passent la validation par catégories (#37). `pere-noel tirage` refuse une édition `drawn`/`revealed` sans `--force-retirage` et annule un tirage dont l'audit est invalide. Le déverrouillage des manches se fait à l'heure de Paris, et le compteur d'essais est sérialisé par `BEGIN IMMEDIATE`. `ruff`, `ruff format`, `mypy` et `bandit` ne signalent rien, les 258 tests passent et le seuil de couverture de 93 % est atteint (93,95 %).

Il ne reste **aucun Blocker ni Major**. Les constats restants sont des fragilités. Le plus notable concerne les transactions : `get_or_assign_pseudo` ouvre un `with conn:` imbriqué. Quand on lui passe la connexion de l'appelant, il valide la transaction `BEGIN IMMEDIATE` de `start_score_defi` en cours de route, ce qui a été vérifié par un script. Le web n'emprunte pas ce chemin aujourd'hui, mais rien ne l'en empêche. Autre point : l'audit du tirage s'exécute après une validation séparée. L'ADR-0005 affirme qu'« un tirage invalide n'est jamais visible des Lutins », mais un court intervalle (ou un plantage) le rend visible.

Côté gouvernance, `uv.lock` est resté à la version 2.0.0, le correctif `ab916b3` n'a pas d'entrée `[Unreleased]` dans le CHANGELOG, aucun tag 2.0.x n'existe et aucune CI ne rejoue les contrôles. La couverture de branches (91,8 %) reste sous le seuil de lignes, et les branches de rejet de `get_manche_attributes`, le garde-fou de #37, ne sont pas couvertes.

---

## Scorecard

| Dimension | Rating | Findings (B/M/m/O) |
|---|---|---|
| Architecture & System Structure | ✅ | 0 Blocker, 0 Major, 2 Minor, 0 Observation |
| Code Quality & Maintainability | ⚠️ | 0 Blocker, 0 Major, 3 Minor, 0 Observation |
| Security & Privacy | ✅ | 0 Blocker, 0 Major, 2 Minor, 3 Observation |
| Performance & Efficiency | ✅ | 0 Blocker, 0 Major, 1 Minor, 1 Observation |
| Release Readiness & Governance | ⚠️ | 0 Blocker, 0 Major, 3 Minor, 0 Observation |

---

## Résultats des outils de vérification

| Commande | Résultat |
|---|---|
| `.venv/Scripts/ruff.exe check .` | ✅ All checks passed! |
| `.venv/Scripts/ruff.exe format --check .` | ✅ 58 files already formatted |
| `.venv/Scripts/mypy.exe source tests` | ✅ Success: no issues found in 31 source files |
| `.venv/Scripts/bandit.exe -c pyproject.toml -r source -q` | ✅ Aucun problème signalé |
| `.venv/Scripts/python.exe -m pytest -q` | ✅ 258 passed en 22,6 s ; couverture lignes **93,95 %** (seuil 93 % atteint) |
| `python -m pytest -q --cov-branch` | ⚠️ 258 passed ; couverture lignes+branches **91,82 %** (sous le seuil de 93 % si les branches étaient comptées). Plus faibles : `helper.py` 85 %, `defi.py` 87 %, `revelation.py` 87 %, `annonce.py` 88 % |
| `uv lock --check` | ❌ `The lockfile at uv.lock needs to be updated` ; `uv lock --dry-run` → `Update pere-noel-fremo v2.0.0 -> v2.0.1` |
| `pip list --outdated` | Mises à jour de correctif seulement : fastapi 0.143.0→0.143.2, starlette 1.7.0→1.8.0, ruff 0.17.0→0.17.1 |
| Script de faisabilité sur une **copie** de `res/fremo.db` | 26 Lutins actifs, 12 à 22 Bénéficiaires admissibles chacun (historique complet), `solve_tirage` réussit 20 fois sur 20 |
| Script de transaction imbriquée (voir premier constat) | `in_transaction after nested get_or_assign_pseudo: False` |

⏸️ **Non vérifié, nécessite l'environnement d'exécution réel :** build et démarrage de l'image Docker, exposition Tailscale Funnel, envoi réel Gmail (jeton OAuth). Procédure : `docker compose build && docker compose up -d`, puis `curl -I https://<funnel>/scores` et `pere-noel annonce --dry-run` suivi d'un envoi ciblé `--target <id> --to <adresse de test>`.

---

## Detailed Findings

### [Minor] `get_or_assign_pseudo` valide la transaction `BEGIN IMMEDIATE` de son appelant
- **Location:** [database.py:758](../../source/pere_noel_fremo/database.py#L758), appelée depuis [database.py:924](../../source/pere_noel_fremo/database.py#L924)
- **Category:** Architecture
- **Description:** `start_score_defi` ouvre `with conn:` + `begin_immediate(conn)`, puis, quand `pseudo_lutin is None`, appelle `get_or_assign_pseudo(conn, …)`. Celle-ci ouvre un second `with conn:` sur la même connexion. Or `Connection.__exit__` valide la transaction : le verrou d'écriture est libéré avant le `SELECT`/`INSERT` de `scores_defi`, qui s'exécutent hors de la transaction immédiate. L'atomicité visée par #41 ne tient donc que si l'appelant fournit le pseudo, ce que fait aujourd'hui le seul appelant web ([web.py:329-348](../../source/pere_noel_fremo/web.py#L329)).
- **Evidence:** script `nested.py` (base temporaire, `start_score_defi(db, 'a', 2026, pseudo_lutin=None)`) → `in_transaction after nested get_or_assign_pseudo: False`.
- **Recommendation:** Dans `get_or_assign_pseudo`, n'ouvrir `with conn:` que lorsqu'elle crée la connexion (`close_after`), et retirer le `CREATE TABLE IF NOT EXISTS pseudos` redondant avec `SCHEMA_SQL` ([database.py:12](../../source/pere_noel_fremo/database.py#L12)). Ajouter un test qui vérifie `conn.in_transaction` après l'appel.

### [Minor] Le tirage invalide est validé avant l'audit : la promesse de l'ADR-0005 n'est pas strictement tenue
- **Location:** [tirage.py:200-207](../../source/pere_noel_fremo/tirage.py#L200), [database.py:603-637](../../source/pere_noel_fremo/database.py#L603)
- **Category:** Architecture
- **Description:** `snapshot_attributions`, `save_attributions`, `audit_tirage` et `restore_attributions` utilisent chacune leur propre connexion. Entre la validation de `save_attributions` (statut `drawn`) et `restore_attributions`, l'Espace Lutin sert la Carte à gratter du tirage invalide. Si le processus s'arrête dans cet intervalle, l'état invalide persiste. L'[ADR-0005, amendement](../../docs/adr/0005-espace-lutin-fastapi-sqlite-et-admin-aveugle.md) affirme pourtant qu'« un tirage invalide n'est jamais visible des Lutins ». L'intervalle dure quelques millisecondes et le tirage est une opération d'administrateur unique, d'où la sévérité Minor.
- **Recommendation:** Auditer la carte `pairs` en mémoire avant toute écriture (les contrôles de bijection, d'exclusion et d'historique ne dépendent que de `confirmed_lutins` et de l'historique), ou exécuter écriture, audit et décision dans une seule transaction et ne valider qu'en cas d'audit valide.

### [Minor] Code mort dans `database.py`
- **Location:** [database.py:959](../../source/pere_noel_fremo/database.py#L959) (`start_manche_defi`), [database.py:865](../../source/pere_noel_fremo/database.py#L865) (`get_or_create_score_defi`), [database.py:962](../../source/pere_noel_fremo/database.py#L962) (`complete_score_defi`), [database.py:1200](../../source/pere_noel_fremo/database.py#L1200) (`backfill_historical_attributions`)
- **Category:** Quality
- **Description:** `start_manche_defi` n'a aucun appelant, ni dans `source/` ni dans `tests/`. Les trois autres fonctions ne sont appelées que par les tests (`grep -rlw` : définition seule dans `source/`). `complete_score_defi` est un second chemin de complétion qui contourne le plafond d'essais et la pénalité de `register_solve_attempt` : si elle était réutilisée, elle rouvrirait la faille fermée par #29.
- **Recommendation:** Supprimer `start_manche_defi` et `complete_score_defi`, adapter les tests à `register_solve_attempt`. Pour `backfill_historical_attributions`, la brancher sur une sous-commande CLI ou la supprimer.

### [Minor] Les branches de rejet du validateur de grilles ne sont pas testées
- **Location:** [defi.py:334-387](../../source/pere_noel_fremo/defi.py#L334)
- **Category:** Quality
- **Description:** `get_manche_attributes` empêche de démarrer le chronomètre d'une manche incohérente (#37). La couverture montre pourtant ses branches de rejet comme non exécutées : lignes 344, 352, 355, 357, 363, 374, 377 (`attributs` vide, solution sans attribut, attributs hétérogènes, catégorie partagée, etc.). La couverture lignes+branches globale vaut 91,82 %, sous le seuil de 93 % que l'on ne mesure qu'en lignes.
- **Evidence:** `pytest --cov-branch` → `defi.py 220 23 98 17 87% … 344, 352, 355, 357, 363, 374, 377`.
- **Recommendation:** Paramétrer un test `pytest.mark.parametrize` sur des grilles défectueuses (une par message de `GrilleInvalideError`), puis activer `--cov-branch` dans `addopts`.

### [Minor] Tables de jours et de mois en double ; manches illisibles ignorées en silence
- **Location:** [defi.py:12-26](../../source/pere_noel_fremo/defi.py#L12) et [helper.py:190-191](../../source/pere_noel_fremo/helper.py#L190) ; [defi.py:293-294](../../source/pere_noel_fremo/defi.py#L293)
- **Category:** Quality
- **Description:** `_JOURS_FR`/`_MOIS_FR` et `FRENCH_DAYS`/`FRENCH_MONTHS` dupliquent les mêmes listes pour deux formateurs de date. Par ailleurs, `get_all_manches` avale `yaml.YAMLError`, `OSError`, `ValueError` et `KeyError` avec un simple `pass` : un fichier `manche_N.yml` mal formé disparaît du calendrier sans aucune trace dans les journaux.
- **Recommendation:** Factoriser les tables dans un seul module (`helper` ou un petit module `dates_fr`). Remplacer le `pass` par `logger.warning("Manche ignorée : %s (%s)", file.name, exc)`.

### [Minor] Révélation : `fullname` injecté sans échappement HTML
- **Location:** [revelation.py:115](../../source/pere_noel_fremo/revelation.py#L115)
- **Category:** Security
- **Description:** #40 a ajouté `html.escape(fullname)` au gabarit d'Annonce ([annonce.py:131](../../source/pere_noel_fremo/annonce.py#L131)), mais `format_revelation_body` remplace toujours `{fullname}` brut. Les noms sont saisis par l'administrateur, donc le risque est faible, mais les deux campagnes divergent.
- **Recommendation:** Appliquer `html.escape` comme pour l'Annonce et ajouter le test miroir de celui de l'Annonce.

### [Minor] `token.json` (jeton de rafraîchissement Gmail) écrit avec les permissions par défaut
- **Location:** [helper.py:104-105](../../source/pere_noel_fremo/helper.py#L104), chemin [helper.py:27-28](../../source/pere_noel_fremo/helper.py#L27)
- **Category:** Security
- **Description:** Le jeton OAuth, qui donne le droit d'envoyer du courrier au nom du compte, est écrit par `open(..., "w")` dans `res/`, répertoire monté dans le conteneur ([docker-compose.yml](../../docker-compose.yml)). Sous Linux, il hérite de l'umask (souvent 0644). `res/*.json` est bien ignoré par git ([.gitignore](../../.gitignore)).
- **Recommendation:** Créer le fichier avec `os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)`.

### [Minor] Handlers `async def` qui exécutent des E/S bloquantes
- **Location:** [web.py:135-268](../../source/pere_noel_fremo/web.py#L135)
- **Category:** Performance
- **Description:** Toutes les routes sont `async def`, mais elles appellent `sqlite3` et lisent des YAML de façon synchrone, donc directement sur la boucle d'événements. Un affichage de l'Espace Lutin lit les 15 fichiers de manche via `get_all_manches` ([web.py:156](../../source/pere_noel_fremo/web.py#L156)), les relit pour le classement ([defi.py:130](../../source/pere_noel_fremo/defi.py#L130)), puis ouvre une connexion SQLite par manche pour `get_score_defi` ([web.py:159](../../source/pere_noel_fremo/web.py#L159)) et une autre par manche déverrouillée pour `get_scores_classement` ([defi.py:138](../../source/pere_noel_fremo/defi.py#L138)). Avec 26 Lutins, cela reste supportable, mais chaque requête bloque toutes les autres pendant sa durée.
- **Recommendation:** Déclarer ces routes en `def` (FastAPI les exécute alors dans un pool de threads ; les transactions `BEGIN IMMEDIATE` et le `timeout` SQLite de 5 s rendent ce passage sûr), ou mettre en cache les manches chargées par `(year, mtime)`.

### [Minor] `uv.lock` désynchronisé de la version 2.0.1
- **Location:** [uv.lock:1291-1292](../../uv.lock#L1291), [pyproject.toml:7](../../pyproject.toml#L7)
- **Category:** Release
- **Description:** Le verrou annonce `pere-noel-fremo 2.0.0` alors que `pyproject.toml` et `__init__.py` sont à 2.0.1. Le Dockerfile utilise `uv export --frozen`, qui ne vérifie pas la cohérence : le build passe, mais le verrou suivi (#42) n'est plus le reflet exact du projet. Le Dockerfile installe en outre `uv` sans version ([Dockerfile:12](../../Dockerfile#L12)).
- **Evidence:** `uv lock --check` → `The lockfile at uv.lock needs to be updated` ; `uv lock --dry-run` → `Update pere-noel-fremo v2.0.0 -> v2.0.1`.
- **Recommendation:** `uv lock` puis valider. Épingler `uv==<version>` dans le Dockerfile. Ajouter un hook pre-commit `uv-lock` (dépôt `astral-sh/uv-pre-commit`) pour garder le verrou à jour.

### [Minor] CHANGELOG sans section `[Unreleased]` pour `ab916b3`, aucun tag 2.0.x
- **Location:** [CHANGELOG.md:8](../../CHANGELOG.md#L8)
- **Category:** Release
- **Description:** Le commit `ab916b3`, postérieur à 2.0.1, change un comportement (annulation et restauration d'un tirage dont l'audit est invalide, affichage des catégories d'erreur) et retire une API (`get_pseudo_for_lutin`). Le CHANGELOG n'en dit rien (`grep -i 'restaur\|annul\|Unreleased'` : aucun résultat). Le dernier tag reste `2024_1.5.0` (`git tag`) : ni 2.0.0 ni 2.0.1 ne sont tagués, constat déjà fait lors de la revue précédente.
- **Recommendation:** Ajouter `## [Unreleased]` avec `Changed` (restauration sur audit invalide) et `Removed` (`get_pseudo_for_lutin`). Taguer les versions publiées en suivant la convention existante (`2026_2.0.1`).

### [Minor] Aucune intégration continue
- **Location:** racine du dépôt (ni `.forgejo/workflows/` ni `.github/workflows/`)
- **Category:** Release
- **Description:** La qualité ne repose que sur les hooks pre-commit locaux ([.pre-commit-config.yaml](../../.pre-commit-config.yaml)). Avec la politique fast-forward-only de l'[ADR-0011](../../docs/adr/0011-politique-de-fusion-fast-forward-only-sur-forgejo.md), rien ne vérifie côté Forgejo qu'une branche rebasée passe encore les tests avant la fusion.
- **Recommendation:** Ajouter un workflow Forgejo Actions minimal : `uv sync --frozen`, `ruff check`, `mypy`, `pytest`, `uv lock --check`. En faire un contrôle requis dans la protection de `master`.

### [Observation] `audit-tirage` désigne nommément l'unique Bénéficiaire admissible
- **Location:** [audit.py:67-71](../../source/pere_noel_fremo/audit.py#L67), affiché par [cli.py:484-487](../../source/pere_noel_fremo/cli.py#L484)
- **Category:** Security
- **Description:** L'avertissement « Contrainte critique » donne l'identifiant du seul Bénéficiaire possible d'un Lutin. Sur un tirage valide, cela revient à révéler sa paire. L'ADR-0005 réserve le détail nominatif à `audit-tirage`, donc ce comportement est conforme. En revanche, l'organisateur qui lance cette commande se gâche la surprise si le Lutin concerné, c'est lui.
- **Recommendation:** Masquer l'identifiant dans l'avertissement (comme `error_categories`), ou ajouter une option `--nominatif`.

### [Observation] Données personnelles réelles suivies dans git
- **Location:** [res/2026/data_in.yml](../../res/2026/data_in.yml) (et les années précédentes)
- **Category:** Security
- **Description:** Les noms complets, les exclusions et l'historique de 9 éditions sont versionnés. Les adresses courriel sont absentes (`email: null`) et `secure_data.yml` est ignoré. Ce choix se défend pour un dépôt privé sur le homelab, mais l'historique git rend toute purge ultérieure coûteuse.

### [Observation] Liens magiques sans expiration ; adresses courriel journalisées
- **Location:** [tokens.py:63-89](../../source/pere_noel_fremo/tokens.py#L63), [helper.py:183](../../source/pere_noel_fremo/helper.py#L183)
- **Category:** Security
- **Description:** Un jeton reste valide indéfiniment pour son édition. Avec 128 bits d'entropie et les jetons masqués dans les journaux d'accès, le risque est faible. `gmail_send_email` journalise `Sent to <adresse>` au niveau INFO.

### [Observation] La contrainte d'historique se resserre chaque année
- **Location:** [database.py:410-423](../../source/pere_noel_fremo/database.py#L410)
- **Category:** Performance
- **Description:** L'historique exclut à vie tout Bénéficiaire déjà offert. Sur la base actuelle, si les 26 Lutins actifs étaient présents, le Lutin le plus contraint n'aurait plus que 12 Bénéficiaires admissibles, et le solveur aléatoire (500 × 2000 essais) réussit 20 fois sur 20. Ce ne sera plus vrai à terme avec un effectif réduit. L'audit détecte déjà les impasses individuelles, mais pas l'absence globale de bijection (condition de Hall).
- **Recommendation:** Le moment venu, limiter l'historique aux N dernières éditions, ou remplacer le solveur par une recherche de couplage parfait qui distingue « impossible » de « malchanceux ».

---

## Ruled-Out Items (Verified Clean)

- **Constats de la revue précédente** : grilles multi-catégories ([defi.py:334](../../source/pere_noel_fremo/defi.py#L334), garde 409 à [web.py:321-327](../../source/pere_noel_fremo/web.py#L321)) ; garde de re-tirage ([tirage.py:168-177](../../source/pere_noel_fremo/tirage.py#L168)) ; heure de Paris ([defi.py:188-194](../../source/pere_noel_fremo/defi.py#L188)) ; compteur atomique ([database.py:1054-1056](../../source/pere_noel_fremo/database.py#L1054)) ; échappement de l'Annonce ([annonce.py:131](../../source/pere_noel_fremo/annonce.py#L131)) ; ADR renumérotée (0012) ; vocabulaire `pseudo_lutin` et migration de colonne ([database.py:126-128](../../source/pere_noel_fremo/database.py#L126)).
- **Grilles 2026** : les 15 fichiers ont un `unlock_at` (fail-closed si le format est invalide, [defi.py:208-220](../../source/pere_noel_fremo/defi.py#L208)).
- **Intégrité du Défi** : indices servis seulement pendant un essai en cours ([web.py:368](../../source/pere_noel_fremo/web.py#L368)) ; `solution` et `indices` retirés du calendrier rendu ([web.py:170-173](../../source/pere_noel_fremo/web.py#L170)) ; chronomètre côté serveur, non redémarrable ([database.py:945](../../source/pere_noel_fremo/database.py#L945)) ; soumissions incomplètes sans consommation d'essai ([web.py:403](../../source/pere_noel_fremo/web.py#L403)) ; point de participation conforme à l'ADR-0007 (1 pt après 3 échecs, 0 pt pour un abandon volontaire, [defi.py:111-116](../../source/pere_noel_fremo/defi.py#L111)).
- **Fuites d'identité** : `lutin_id` retiré du tableau public ([web.py:120-129](../../source/pere_noel_fremo/web.py#L120)) ; les gabarits n'affichent que `lutin.fullname` et `beneficiaire.fullname` du Lutin connecté, avec l'auto-échappement Jinja ; aucune ressource externe chargée par les gabarits ni la CSS (pas de fuite du jeton par `Referer`) ; jetons masqués dans les journaux d'accès ([web.py:52-75](../../source/pere_noel_fremo/web.py#L52)).
- **Admin aveugle au tirage** : le résumé console et les journaux n'exposent ni paire ni identifiant ([tirage.py:31-64](../../source/pere_noel_fremo/tirage.py#L31), [tirage.py:209-221](../../source/pere_noel_fremo/tirage.py#L209)).
- **Entrées non fiables** : `manche_id` et `year` typés `int` par FastAPI, donc pas de traversée de chemin dans `manche_{id}.yml` ; YAML chargé exclusivement par `yaml.safe_load` ; toutes les requêtes SQL sont paramétrées (`grep -n 'execute(f'` : aucun résultat ; la seule concaténation, `sql +=` à [database.py:438-439](../../source/pere_noel_fremo/database.py#L438), n'ajoute que des fragments constants).
- **Secrets** : `secure_data.yml`, `credentials.json`, `token.json`, `*.db` ignorés ([.gitignore](../../.gitignore)) ; hook `detect-private-key` actif ; jetons générés par `secrets.token_urlsafe(16)` ([tokens.py:10](../../source/pere_noel_fremo/tokens.py#L10)) ; pseudos tirés par `secrets.choice` ([database.py:792](../../source/pere_noel_fremo/database.py#L792)).
- **Conteneur** : utilisateur non privilégié `lutin` ([Dockerfile](../../Dockerfile)), port lié au loopback ([docker-compose.yml](../../docker-compose.yml)), `.dockerignore` exclut `.venv`, caches et `.git`.
- **Gmail** : mode non interactif par défaut, sans `run_local_server` bloquant ([helper.py:100-101](../../source/pere_noel_fremo/helper.py#L100)) ; service construit une seule fois par campagne ([revelation.py:194-196](../../source/pere_noel_fremo/revelation.py#L194)) ; statut `revealed` posé seulement après un envoi nominal complet ([revelation.py:252-254](../../source/pere_noel_fremo/revelation.py#L252)).
- **Hygiène Python** : aucun `time.sleep` dans `source/` ni `tests/` ; aucun `print` hors de `cli.py` ; aucun argument par défaut mutable ; connexions SQLite toujours fermées dans un `finally`.
