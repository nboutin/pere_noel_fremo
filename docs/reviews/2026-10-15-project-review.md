# Project Review: Le Père Noël de la Frémo (Full Audit)

**Date:** 2026-10-15
**Commit:** 8a2c44c (arbre de travail propre)
**Stack Profile:** Python (3.10+, FastAPI + SQLite)
**Reviewer:** AI Pair Programmer

## Executive Summary

Les 18 constats de la revue du 2026-10-13 ont été traités dans les tickets #25 à #34, et la vérification le confirme pour l'essentiel. Les indices ne sont plus livrés dans la page. Les pseudos sont tirés sans remise et le classement est indexé par `lutin_id`. Les soumissions sont plafonnées à 3, avec 15 s de pénalité par essai faux. Les échecs Gmail remontent, `import web` n'a plus d'effet de bord et le conteneur tourne en utilisateur non privilégié, sur le loopback. L'outillage est propre : `ruff`, `ruff format`, `mypy` et `bandit` passent sans erreur, et les 123 tests passent.

Il reste un **défaut bloquant à échéance très courte**. Le formulaire de grille et le validateur côté serveur figent les clés `luge` et `friandise`. Or 10 des 15 manches de 2026 utilisent d'autres catégories (`bonnets`/`cadeaux`, `instruments`/`boissons`). Pour ces manches, l'interface n'affiche aucune option et le serveur rejette même la solution exacte du YAML. Un Lutin qui clique sur « Démarrer » lance un chronomètre qu'il ne peut pas arrêter, sauf en abandonnant, ce qui vaut 0 point. La manche 2 est la première touchée. Elle se déverrouille le **lundi 19 octobre 2026**, dans 4 jours. Aucun test ne couvre une grille dont les catégories ne sont pas luge/friandise.

Le second point important est que `pere-noel tirage` peut être relancé sur une édition déjà `drawn`. Il refait alors le tirage en silence, même après que les Lutins ont gratté leur carte. Le reste relève de l'hygiène : l'heure de déverrouillage est interprétée en UTC au lieu de l'heure de Paris, le CHANGELOG 2.0.0 décrit des commandes qui n'existent pas, l'environnement de développement a dérivé et deux ADR portent le numéro 0010.

---

## Scorecard

| Dimension | Rating | Findings (B/M/m/O) |
|---|---|---|
| Architecture & System Structure | ⚠️ | 0 Blocker, 1 Major, 1 Minor, 0 Observation |
| Code Quality & Maintainability | ❌ | 1 Blocker, 0 Major, 1 Minor, 1 Observation |
| Security & Privacy (incl. intégrité du Défi) | ✅ | 0 Blocker, 0 Major, 0 Minor, 1 Observation |
| Performance & Efficiency | ✅ | 0 Blocker, 0 Major, 1 Minor, 2 Observation |
| Release Readiness & Governance | ⚠️ | 0 Blocker, 0 Major, 3 Minor, 0 Observation |

---

## Résultats des outils de vérification

| Commande | Résultat |
|---|---|
| `.venv/Scripts/ruff.exe check .` | ✅ All checks passed! |
| `.venv/Scripts/ruff.exe format --check .` | ✅ 49 files already formatted |
| `.venv/Scripts/mypy.exe source tests` | ✅ Success: no issues found in 23 source files |
| `.venv/Scripts/bandit.exe -c pyproject.toml -r source -q` | ✅ Aucun problème signalé |
| `.venv/Scripts/python.exe -m pytest -q` | ✅ 123 passed, 1 warning (`StarletteDeprecationWarning`, voir Observation) en 12,6 s |
| `pytest --cov=pere_noel_fremo` | ❌ `unrecognized arguments: --cov` : `pytest-cov` est déclaré dans `[dev]` mais absent du venv (`pip show pytest-cov` → not found) |
| `pytest --cov=pere_noel_fremo --cov-branch` (après `pip install pytest-cov`, 7.1.0) | ✅ **88 %** (1504 instructions, 516 branches). Plus faibles : `cli.py` 75 %, `helper.py` 77 % (`load_credentials` 83-95 jamais exécuté), `audit.py` 80 %. `defi.py:333` (branche « incomplète » de `is_solution_complete`, cœur du Blocker) non couverte. |

Les scripts de reproduction ont tourné sur une base SQLite temporaire, avec les vraies grilles `res/2026/grilles/` en lecture seule. `res/fremo.db` n'a pas été touchée.

---

## Detailed Findings

### [Blocker] 10 manches sur 15 sont injouables : l'interface et le validateur figent `luge`/`friandise`
- **Location:** [espace_lutin.html:236-262](../../source/pere_noel_fremo/templates/espace_lutin.html#L236-L262), [espace_lutin.html:664-672](../../source/pere_noel_fremo/templates/espace_lutin.html#L664-L672), [defi.py:318-336](../../source/pere_noel_fremo/defi.py#L318-L336), [manche_2.yml](../../res/2026/grilles/manche_2.yml)
- **Category:** Quality (violation de spécification, défaut visible)
- **Description:** Le gabarit génère les listes déroulantes à partir de `active_manche.categories.luges` et `categories.friandises`, et la soumission construit `{luge, friandise}`. Côté serveur, `is_solution_complete` exige `entry.get("luge")` et `entry.get("friandise")` ([defi.py:334](../../source/pere_noel_fremo/defi.py#L334)). Les grilles 2, 3, 5, 6, 8, 9, 11, 12, 14 et 15 utilisent `bonnets`/`cadeaux` (solution `{bonnet, cadeau}`) ou `instruments`/`boissons` (`{instrument, boisson}`). Résultat pour ces manches :
  1. l'interface n'affiche **aucune option**, et le Lutin ne peut pas remplir la grille ;
  2. la solution exacte du YAML est rejetée comme « incomplète » ;
  3. une réponse correcte au format de l'interface est comptée comme fausse, et la manche est scellée au 3e essai.

  `POST /start` réussit quand même, donc le chronomètre tourne et seul l'abandon (0 pt selon [ADR 0007:22](../adr/0007-championnat-multi-manches-defi-du-lutin.md#L22)) est possible. La manche 2 se déverrouille le **2026-10-19 19:00**. Aucun test ne couvre une grille dont les catégories ne sont pas luge/friandise (`grep bonnet|instrument tests/` ne trouve que des noms de personnes).
- **Evidence:** reproduction, horloge fixée au 2026-10-20 :
  ```
  manche1 options: 18
  options rendered in grid: []                         # manche 2
  start: 200
  solve with EXACT YAML solution -> 400 {'detail': 'La solution soumise est incomplète (...)'}
  solve with UI-shaped correct answer #1 -> 400 ... Essais restants : 2/3 (pénalité accumulée : +15s).
  solve with UI-shaped correct answer #3 -> 400 Nombre maximal d'essais atteint (3/3). La manche est scellée.
  ```
  Répartition des catégories par fichier : `lutins/luges/friandises` pour 1, 4, 7, 10, 13 ; `lutins/bonnets/cadeaux` pour 2, 5, 8, 11, 14 ; `lutins/instruments/boissons` pour 3, 6, 9, 12, 15.
- **Recommendation:** Rendre la grille générique, **avant le 19 octobre**. Dériver les attributs des clés de `categories` hors `lutins`, avec un mappage pluriel → singulier explicite dans le YAML (par exemple `attributs: {bonnet: bonnets, cadeau: cadeaux}`), plutôt que par convention. Faire générer les `<select>` et le JSON soumis par le gabarit en itérant sur ces attributs. Faire vérifier par `is_solution_complete` les attributs de `solution`, pas des noms figés. Ajouter un test paramétré `test_web` qui démarre puis résout **chaque** manche de `res/2026/grilles/` avec sa solution YAML, ainsi qu'un test de chargement qui vérifie la cohérence `categories`/`solution` de chaque fichier. En mesure d'urgence, refuser `start` (409) sur une manche dont les catégories ne sont pas supportées, plutôt que de lancer un chronomètre impossible à arrêter.

### [Major] `pere-noel tirage` refait le tirage en silence sur une édition déjà `drawn`
- **Location:** [tirage.py:141-171](../../source/pere_noel_fremo/tirage.py#L141-L171), [database.py:582-619](../../source/pere_noel_fremo/database.py#L582-L619), [cli.py:329-346](../../source/pere_noel_fremo/cli.py#L329-L346)
- **Category:** Architecture (garde d'état manquante)
- **Description:** `run_tirage` ne lit pas le statut de l'édition. Un second `pere-noel tirage --year 2026` après le tirage refait les paires et les réécrit. Les Lutins qui ont déjà gratté leur carte ont donc un Bénéficiaire périmé, et en mode Admin aveugle l'administrateur ne peut pas le savoir. De plus, `save_attributions` ne supprime que les donneurs présents dans la **nouvelle** carte. Un donneur absent du second tirage garde sa ligne de l'année précédente, et son ancien Bénéficiaire peut alors avoir deux donneurs. `audit-tirage` le détecterait, mais seulement si on pense à le lancer.
- **Evidence:**
  ```
  first ok: True second ok: True | pairs changed: 5 / 6
  ```
- **Recommendation:** Dans `run_tirage`, refuser un tirage si le statut est `drawn` ou `revealed`, sauf drapeau explicite `--force-retirage` qui demande confirmation. Dans `save_attributions`, faire un `DELETE FROM attributions WHERE year = ?` global avant les insertions. Lancer `audit_tirage` automatiquement après `save_attributions` et faire échouer la commande si l'audit est invalide.

### [Minor] L'heure de déverrouillage est interprétée en UTC, pas en heure de Paris
- **Location:** [defi.py:206-207](../../source/pere_noel_fremo/defi.py#L206-L207), [ADR 0007:10](../adr/0007-championnat-multi-manches-defi-du-lutin.md#L10)
- **Category:** Quality
- **Description:** Les `unlock_at` des grilles sont naïfs (`'2026-10-19 19:00:00'`) et `is_manche_unlocked` leur attribue `timezone.utc`. L'ADR annonce un déverrouillage « chaque lundi à 19h00 », à l'heure locale des participants. Les manches s'ouvrent donc à 21h00 jusqu'au 25 octobre (CEST), puis à 20h00 (CET). Le Tableau des scores affiche « 🔒 2026-10-19 19:00:00 », ce qui laisse croire à une ouverture à 19h.
- **Evidence:**
  ```
  2026-10-19T19:30:00+02:00 LOCKED
  2026-10-19T20:30:00+02:00 LOCKED
  2026-10-19T21:30:00+02:00 unlocked
  ```
- **Recommendation:** Interpréter les dates naïves dans `Europe/Paris` (`zoneinfo`, en ajoutant `tzdata` aux dépendances, car le venv Windows n'a pas de base de fuseaux : `ZoneInfoNotFoundError` pendant la revue), ou écrire les `unlock_at` en ISO avec décalage (`2026-10-19T19:00:00+02:00`). Ajouter un test sur le cas du changement d'heure.

### [Minor] Dérive de l'outillage : dépendances non bornées, verrou ignoré, venv désynchronisé
- **Location:** [pyproject.toml:9-17](../../pyproject.toml#L9-L17), [.gitignore:21](../../.gitignore#L21), [Dockerfile:14](../../Dockerfile#L14)
- **Category:** Architecture (build)
- **Description:** Aucune dépendance d'exécution n'a de borne (`fastapi`, `uvicorn`, `google-api-python-client`…), et `uv.lock` est exclu par `.gitignore`. Le `pip install .` du Dockerfile installe donc les dernières versions au moment du build. Le venv local n'a pas `pytest-cov`, pourtant déclaré dans `[dev]`, ce qui empêche toute mesure de couverture.
- **Recommendation:** Suivre `uv.lock` (ou un `requirements.lock` produit par `pip-compile`), et l'utiliser dans le Dockerfile. Ajouter des bornes inférieures aux dépendances d'exécution. Lancer `pip install -e .[dev]` (ou `uv sync --extra dev`) pour réaligner le venv, puis ajouter `--cov` au hook pytest ou à la CI.

### [Minor] Annonce : identifiants OAuth rechargés et flux interactif possible à chaque courriel
- **Location:** [helper.py:76-96](../../source/pere_noel_fremo/helper.py#L76-L96), [helper.py:152-157](../../source/pere_noel_fremo/helper.py#L152-L157), [annonce.py:240-255](../../source/pere_noel_fremo/annonce.py#L240-L255)
- **Category:** Performance (fiabilité de la campagne)
- **Description:** `gmail_send_email` appelle `load_credentials()` et `build("gmail", "v1")` à chaque destinataire. Si le jeton n'est pas rafraîchissable, `flow.run_local_server(port=0)` est lancé **dans la boucle**, une fois par Lutin. Dans le conteneur du Homelab, sans navigateur, le premier appel bloque sans délai d'expiration et la campagne ne progresse plus. L'erreur n'est jamais remontée.
- **Recommendation:** Charger les identifiants et construire le service une seule fois en début de campagne, puis passer le service à `gmail_send_email`. Ajouter un paramètre `interactive=False` qui lève une `EmailSendError` explicite au lieu d'ouvrir le flux OAuth quand le jeton est invalide.

### [Minor] CHANGELOG 2.0.0 inexact et absence de tag
- **Location:** [CHANGELOG.md:13-15](../../CHANGELOG.md#L13-L15), [tirage.py:5](../../source/pere_noel_fremo/tirage.py#L5), [cli.py:381-390](../../source/pere_noel_fremo/cli.py#L381-L390)
- **Category:** Release
- **Description:** Le CHANGELOG annonce les sous-commandes `stats`, `defi`, `lutin` et `backfill`, mais `main` ne connaît que `init-db`, `annonce`, `serve`, `tirage` et `audit-tirage`. Il décrit un « tirage aveugle cryptographique » alors que le solveur utilise `random.randint` (Mersenne Twister, B311 ignoré exprès dans `pyproject.toml`), et un « rendu SVG anti-OCR » alors que les indices sont dessinés sur `<canvas>`. Il manque `init-db` et `audit-tirage`. Le dernier tag est `2024_1.5.0` : il n'y a pas de `2026_2.0.0`.
- **Recommendation:** Corriger ces trois lignes, et ajouter une section `[Unreleased]` pour le correctif des grilles. Créer le tag `2026_2.0.0` sur `c6404d4` (ou sur le commit de correctif, en 2.0.1).

### [Minor] Vocabulaire `pseudo_lugeur` encore omniprésent malgré le ticket #31
- **Location:** [database.py:62](../../source/pere_noel_fremo/database.py#L62), [web.py:244-245](../../source/pere_noel_fremo/web.py#L244-L245), [espace_lutin.html:342](../../source/pere_noel_fremo/templates/espace_lutin.html#L342), [GLOSSARY.md:95](../../GLOSSARY.md#L95)
- **Category:** Release (alignement glossaire)
- **Description:** La revue précédente a été close avec « migration du vocabulaire vers `pseudo_lutin` ». Le terme `lugeur` reste pourtant présent 46 fois dans `source/` : 24 dans `database.py`, 9 dans `web.py`, 6 dans `defi.py` et 7 dans les gabarits. La colonne SQL s'appelle toujours `pseudo_lugeur`, les réponses JSON doublent chaque clé (`pseudo_lutin` et `pseudo_lugeur`), et la page affiche « Aucun lugeur n'a encore enregistré de score ». Le glossaire range « Pseudo de lugeur » dans _Avoid_. La fonction `generate_pseudo_lugeur` est dépréciée mais toujours exportée.
- **Recommendation:** Migrer la colonne (`ALTER TABLE scores_defi RENAME COLUMN pseudo_lugeur TO pseudo_lutin`, SQLite ≥ 3.25), supprimer les clés dupliquées des réponses JSON et du contexte de gabarit, et retirer `generate_pseudo_lugeur` et son alias s'ils ne servent qu'aux tests.

### [Minor] Deux ADR portent le numéro 0010
- **Location:** [0010-compatibilite-email-html-et-bulletproof-templates.md](../adr/0010-compatibilite-email-html-et-bulletproof-templates.md), [0010-date-du-repas-de-noel-dans-espace-lutin.md](../adr/0010-date-du-repas-de-noel-dans-espace-lutin.md)
- **Category:** Release
- **Description:** Deux décisions distinctes partagent le même numéro, ce qui rend toute référence « ADR 0010 » ambiguë. Le numéro 0011 est déjà pris par la politique fast-forward.
- **Recommendation:** Renuméroter la plus récente en 0012 et mettre à jour les liens éventuels.

### [Observation] `register_solve_attempt` n'est atomique que grâce à la sérialisation de la boucle d'événements
- **Location:** [database.py:978-1077](../../source/pere_noel_fremo/database.py#L978-L1077), [web.py:362](../../source/pere_noel_fremo/web.py#L362)
- **Category:** Performance (concurrence)
- **Description:** La fonction fait un `SELECT attempts`, puis un `UPDATE attempts = n+1`, dans une transaction SQLite différée. Les handlers sont des `async def` qui font des I/O SQLite synchrones, donc uvicorn (un seul worker) traite les requêtes une à une, et la course est impossible aujourd'hui. Mais passer les handlers en `def`, ce que recommandait la revue précédente pour ne plus bloquer la boucle, ou ajouter des workers rouvrirait la course : N soumissions parallèles liraient toutes `attempts = 0` et contourneraient le plafond de 3.
- **Recommendation:** Ouvrir la transaction en `BEGIN IMMEDIATE`, ou faire un `UPDATE ... SET attempts = attempts + 1 WHERE ... AND completed_at IS NULL RETURNING attempts` (SQLite ≥ 3.35), avant tout changement de modèle d'exécution.

### [Observation] Coût d'un affichage de l'Espace Lutin
- **Location:** [web.py:152-190](../../source/pere_noel_fremo/web.py#L152-L190), [defi.py:132-140](../../source/pere_noel_fremo/defi.py#L132-L140)
- **Category:** Performance
- **Description:** Inchangé depuis la revue précédente, qui l'a accepté : 15 `get_score_defi` (une connexion chacun), plus `calculate_championship_standings` (15 requêtes et 15 lectures YAML), plus un second `get_all_manches`. C'est négligeable pour une trentaine de Lutins.

### [Observation] Gabarit d'Annonce : `fullname` injecté sans échappement HTML
- **Location:** [annonce.py:127-134](../../source/pere_noel_fremo/annonce.py#L127-L134)
- **Category:** Security
- **Description:** `format_annonce_body` fait un `str.replace("{fullname}", fullname)` dans du HTML. La source est `data_in.yml`, contrôlé par l'administrateur, donc le risque est faible. Un nom contenant `<` ou `&` casserait toutefois le rendu.
- **Recommendation:** `html.escape(fullname)` (le Lien magique est déjà url-safe).

### [Observation] Avertissement de dépréciation Starlette dans la suite de tests
- **Location:** [test_web.py:7](../../tests/test_web.py#L7)
- **Category:** Quality
- **Description:** `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.` C'est sans effet aujourd'hui, mais le `TestClient` cassera lors d'une future montée de Starlette, que rien n'empêche faute de borne (voir finding outillage).
- **Recommendation:** Suivre la migration recommandée par Starlette, ou borner `starlette`/`fastapi` en attendant.

---

## Suivi de la revue du 2026-10-13

| Constat précédent | État vérifié | Preuve |
|---|---|---|
| Fuite des indices (Blocker) | ✅ Corrigé | Le GET retire `indices`/`solution` ([web.py:166-167](../../source/pere_noel_fremo/web.py#L166-L167)) ; indices servis seulement après `started_at` ([web.py:342-360](../../source/pere_noel_fremo/web.py#L342-L360)) |
| Collision de pseudos (Blocker) | ✅ Corrigé | Table `pseudos` `UNIQUE (year, pseudo)`, `secrets.choice` sans remise ([database.py:663-728](../../source/pere_noel_fremo/database.py#L663-L728)) ; classement indexé par `lutin_id` ([defi.py:146](../../source/pere_noel_fremo/defi.py#L146)) |
| Force brute (Major) | ✅ Corrigé | Reproduit : scellement à 3/3 et pénalité de +15 s par essai faux |
| Échec Gmail masqué (Major) | ✅ Corrigé | `EmailSendError` levée ([helper.py:160-162](../../source/pere_noel_fremo/helper.py#L160-L162)) ; `sent_at` posé après succès seulement ([annonce.py:248](../../source/pere_noel_fremo/annonce.py#L248)) ; code retour 1 si échecs |
| Pseudos calculables (Major) | ✅ Corrigé | `generate_pseudo_lugeur` n'est plus appelé en production (seulement exporté, voir finding vocabulaire) |
| Chronomètre à la seconde | ✅ Corrigé | `now_dt.isoformat()` avec microsecondes ([database.py:849-850](../../source/pere_noel_fremo/database.py#L849-L850)) |
| Création de scores sur GET | ✅ Corrigé | `get_score_defi` en lecture seule sur le GET ; purge `started_at IS NULL` ([database.py:189](../../source/pere_noel_fremo/database.py#L189)) |
| Effet de bord `import web` | ✅ Corrigé | Plus d'instance `app` au niveau module ; `init_db` ferme sa connexion ([database.py:265-266](../../source/pere_noel_fremo/database.py#L265-L266)) |
| Duplication `RES_DIR` | ✅ Corrigé | [config.py](../../source/pere_noel_fremo/config.py) seule source ; les `__getattr__` de module ne font que déléguer |
| Pipelines legacy | ✅ Corrigé | `email_tossing.py` et `email_annonce.py` absents de `git ls-files` |
| Backfill nominatif | ✅ Corrigé | [m2026_10_backfill.py](../../source/pere_noel_fremo/migrations/m2026_10_backfill.py) ; `purge_year=None` par défaut |
| `order_index` incrémenté | ✅ Corrigé | `DELETE` avant `MAX` ([database.py:590-599](../../source/pere_noel_fremo/database.py#L590-L599)), mais voir le Major sur le re-tirage |
| Exposition réseau / root | ✅ Corrigé | `USER lutin`, `127.0.0.1:8000:8000`, `TokenMaskingFilter` |
| Alternative texte | ✅ Corrigé | `format_annonce_text` contient le Lien magique |
| CHANGELOG et version | 🟡 Partiel | 2.0.0 publié, mais contenu inexact et sans tag (voir finding) |
| Dates ADR 0007 et vocabulaire | 🟡 Partiel | Dates et `CHECK (status IN ...)` corrigés ; vocabulaire `lugeur` toujours présent (voir finding) |
| Hygiène de l'outillage | 🟡 Partiel | `scratch/` ignoré, hook pytest portable, deps mypy complètes ; venv désynchronisé et pas de verrou (voir finding) |

---

## ⏸️ Non vérifié : nécessite l'environnement d'exécution réel

- **Envoi Gmail réel depuis le conteneur.** Procédure : `docker exec pere_noel_fremo pere-noel annonce --lutin <id> --override-email <adresse de test>`, puis vérifier la réception et `tokens.sent_at`. Recommencer avec un `token.json` révoqué pour observer le comportement de `run_local_server` sans navigateur.
- **Exposition Tailscale Funnel et liaison loopback.** Procédure : `curl -I https://<funnel>/scores` depuis l'extérieur, puis `curl http://<ip-lan-homelab>:8000/`, qui doit être refusé.
- **Rendu Canvas anti-OCR et rideau `onblur` sur iOS et Android.** Procédure : jouer la manche 1 sur un téléphone de chaque plateforme, changer d'onglet pendant l'essai et vérifier le rideau.

---

## Ruled-Out Items (Verified Clean)

- **Injection SQL** : toutes les requêtes de [database.py](../../source/pere_noel_fremo/database.py) et [tokens.py](../../source/pere_noel_fremo/tokens.py) sont paramétrées par `?`, y compris les nouvelles (`pseudos`, `register_solve_attempt`, `get_scores_classement`). Aucune f-string dans du SQL.
- **Cohérence des grilles 2026** : pour les 15 fichiers, les clés de `solution` correspondent à `categories.lutins`, et les valeurs de chaque attribut forment une permutation de la catégorie correspondante (script de vérification). Chaque grille compte 4 indices.
- **Fuite d'indices ou de solutions dans le HTML** : `/scores` ne rend que `m.id`, `m.title` et `m.unlock_at` ([tableau_scores.html:92-102](../../source/pere_noel_fremo/templates/tableau_scores.html#L92-L102)). L'Espace Lutin ne passe en JS que `LUTIN_NAMES` via `| tojson` ([espace_lutin.html:358](../../source/pere_noel_fremo/templates/espace_lutin.html#L358)). `lutin_id` est retiré du contexte de `/scores` ([web.py:116-117](../../source/pere_noel_fremo/web.py#L116-L117)).
- **Contrôles d'accès** : `start/solve/abandon/indices` passent par `_get_lutin_and_manche_or_raise` (présence + déverrouillage). `beneficiaire` exige `drawn|revealed`. `presence` est verrouillée après le tirage. Un jeton inconnu donne 404.
- **Règle d'abandon** : 0 point pour un abandon volontaire et 1 point après 3 échecs ([defi.py:113-115](../../source/pere_noel_fremo/defi.py#L113-L115)), conformément à [ADR 0007:21-22](../adr/0007-championnat-multi-manches-defi-du-lutin.md#L21-L22).
- **Secrets dans Git** : `git ls-files` ne contient ni `secure_data.yml`, ni `token.json`, ni `*.json` sous `res/`, ni `*.db`. Les scripts `poc/` ne référencent que `token.json` et `credentials.json` locaux, et des adresses d'exemple Google (`workspacesamples.dev`).
- **Jetons** : `secrets.token_urlsafe(16)` ([tokens.py:9](../../source/pere_noel_fremo/tokens.py#L9)). Le masquage dans les journaux couvre `/lutin/` et `/api/lutin/` ([web.py:49-72](../../source/pere_noel_fremo/web.py#L49-L72)).
- **Admin aveugle** : `get_masked_summary` et le `logger.info` de `run_tirage` n'impriment aucune paire.
- **Audit du tirage** : la règle `matching_count > 1` ([audit.py:110-112](../../source/pere_noel_fremo/audit.py#L110-L112)) est correcte, puisque l'historique inclut l'attribution de l'année auditée.
- **Gestion des ressources** : chaque connexion est fermée dans un `finally`, `init_db` compris. Tous les fichiers sont ouverts avec `with`.
- **Arguments par défaut mutables** : aucun dans `source/` (les `default=[]` d'`argparse` ne sont pas concernés).
- **Tests fragiles** : aucun `time.sleep` dans `tests/`. L'horloge est injectée dans `create_app(clock=...)` et dans les fonctions de score.
- **Conteneur** : image `python:3.12-slim`, utilisateur UID 1000, `PYTHONDONTWRITEBYTECODE`, `.dockerignore` excluant `.git`, `.venv`, `scratch/` et `logs/`.

---

## Suivi des constats (Revue 2026-10-15)

Constats traités par la spécification [#36](https://homelab.tail7d8b91.ts.net:8443/nbt1/pere_noel_fremo/issues/36) et ses tickets #37 à #45 :

| Réf. Constat | Catégorie | Sévérité | Ticket associé | Statut | Résolution |
|---|---|---|---|---|---|
| **Manches 2, 3, 5, 6, 8, 9, 11, 12, 14, 15 injouables** | Quality | **Blocker** | [#37](https://homelab.tail7d8b91.ts.net:8443/nbt1/pere_noel_fremo/issues/37) | ✅ Fermé | Grille générée à partir des attributs de chaque manche, validation des attributs réels, `start` refusé sur manche incohérente. |
| **Re-tirage silencieux d'une édition `drawn`** | Architecture | **Major** | [#38](https://homelab.tail7d8b91.ts.net:8443/nbt1/pere_noel_fremo/issues/38) | ✅ Fermé | Garde d'état avec drapeau explicite, remplacement atomique de l'année, audit automatique après scellement. |
| **Déverrouillage en UTC au lieu de Paris** | Quality | **Minor** | [#39](https://homelab.tail7d8b91.ts.net:8443/nbt1/pere_noel_fremo/issues/39) | ✅ Fermé | `unlock_at` naïf lu en `Europe/Paris`, `tzdata` ajouté, date affichée en français. |
| **Annonce : identifiants OAuth rechargés, flux interactif** | Performance | **Minor** | [#40](https://homelab.tail7d8b91.ts.net:8443/nbt1/pere_noel_fremo/issues/40) | ✅ Fermé | Service Gmail unique par campagne, mode non interactif, échappement HTML de `fullname`. |
| **`register_solve_attempt` atomique par hasard** | Performance | **Observation** | [#41](https://homelab.tail7d8b91.ts.net:8443/nbt1/pere_noel_fremo/issues/41) | ✅ Fermé | Transactions `BEGIN IMMEDIATE`, tests concurrents. |
| **Dérive de l'outillage** | Architecture | **Minor** | [#42](https://homelab.tail7d8b91.ts.net:8443/nbt1/pere_noel_fremo/issues/42) | ✅ Fermé | Bornes, `uv.lock` suivi, Dockerfile sur verrou, couverture mesurée, avertissement Starlette filtré. |
| **Vocabulaire `pseudo_lugeur`** | Release | **Minor** | [#43](https://homelab.tail7d8b91.ts.net:8443/nbt1/pere_noel_fremo/issues/43) | ✅ Fermé | Colonne migrée, clés et alias legacy retirés. |
| **Couverture insuffisante de l'audit et de la CLI** | Quality | **Minor** | [#45](https://homelab.tail7d8b91.ts.net:8443/nbt1/pere_noel_fremo/issues/45) | ✅ Fermé | Tests des chemins d'erreur, couverture portée à 93,6 %. |
| **CHANGELOG 2.0.0 inexact, absence de tag, ADR 0010 en double** | Release | **Minor** | [#44](https://homelab.tail7d8b91.ts.net:8443/nbt1/pere_noel_fremo/issues/44) | ✅ Fermé | CHANGELOG corrigé, entrée 2.0.1, ADR renumérotée en 0012, version 2.0.1 ; tags proposés à l'humain. |
