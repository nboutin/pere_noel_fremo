# Project Review: Le Père Noël de la Frémo (Full Audit)

**Date:** 2026-10-13
**Commit:** adc2424 (+ modifications non commitées sur `annonce.py`, `helper.py`, `GLOSSARY.md`, et `res/2026/annonce.txt` non suivi)
**Stack Profile:** Python (3.10+, FastAPI + SQLite)
**Reviewer:** AI Pair Programmer

## Executive Summary

Depuis la revue du 2026-10-11, le projet a beaucoup changé. Ce n'est plus un script de tirage plus envoi Gmail : c'est maintenant une application FastAPI/SQLite (Espace Lutin, Lien magique, Confirmation de présence, Carte à gratter, championnat du Défi du lutin en 15 manches), administrée par une CLI unifiée `pere-noel` et déployée sur un Homelab exposé via Tailscale Funnel. L'outillage est sain : `ruff`, `ruff format`, `mypy` et `bandit` passent sur `source/` et `tests/`, et les 73 tests passent. Les accès SQL sont tous paramétrés et les jetons sont générés avec `secrets`.

En revanche, le **Défi du lutin**, qui décide qui ouvre son cadeau en premier, n'est pas équitable aujourd'hui. Trois défauts ont été reproduits par script pendant la revue : (1) n'importe quel Lutin peut lire les indices des manches encore verrouillées via `?manche=N` ; (2) l'API de validation accepte un nombre illimité de soumissions, et une grille 3×3 (36 combinaisons) est forcée en 17 essais pour un temps officiel de 1,1 s ; (3) le Pseudo de lutin, déterministe et sans sel, provoque une **collision réelle** dans l'effectif 2026 (`jdenis` et `mdenis` → « Marmotte Polaire »), et le classement fusionne les points des deux Lutins.

Côté envoi, `helper.gmail_send_email` avale toutes les exceptions. Une campagne d'Annonce dont l'authentification Gmail échoue rapporte donc « N courriels envoyés » et horodate `sent_at`, alors que rien n'est parti. Le reste relève de l'hygiène : résolution de `RES_DIR` dupliquée cinq fois, modules legacy qui doublonnent le tirage, effet de bord à l'import de `web.py`, CHANGELOG et version non mis à jour pour toute la partie web.

---

## Scorecard

| Dimension | Rating | Findings (B/M/m/O) |
|---|---|---|
| Architecture & System Structure | ⚠️ | 0 Blocker, 0 Major, 3 Minor, 0 Observation |
| Code Quality & Maintainability | ❌ | 1 Blocker, 1 Major, 5 Minor, 0 Observation |
| Security & Privacy (incl. intégrité du Défi) | ❌ | 1 Blocker, 2 Major, 1 Minor, 1 Observation |
| Performance & Efficiency | ✅ | 0 Blocker, 0 Major, 0 Minor, 1 Observation |
| Release Readiness & Governance | ⚠️ | 0 Blocker, 0 Major, 3 Minor, 0 Observation |

---

## Résultats des outils de vérification

| Commande | Résultat |
|---|---|
| `.venv/Scripts/ruff.exe check source tests` | ✅ All checks passed |
| `.venv/Scripts/ruff.exe check .` | ❌ 6 erreurs, toutes dans `scratch/renew_token.py` (non suivi, non ignoré) |
| `.venv/Scripts/ruff.exe format --check .` | ❌ 1 fichier : `scratch/renew_token.py` ; 48 fichiers conformes |
| `.venv/Scripts/mypy.exe source tests` | ✅ Success: no issues found in 21 source files |
| `.venv/Scripts/bandit.exe -c pyproject.toml -r source` | ✅ Aucun problème (seulement l'avertissement `nosec B105` attendu sur `helper.py:39`) |
| `.venv/Scripts/pytest.exe -q` | ✅ 73 passed, 1 warning (`StarletteDeprecationWarning` : httpx déprécié dans `TestClient`) en 11,8 s |
| `pytest --cov` | ⏸️ Non exécuté : `pytest-cov` n'est pas installé dans le venv |

Les scripts de reproduction (`repro.py`, `repro2.py`) ont tourné sur des bases SQLite temporaires. Ils n'ont pas touché `res/fremo.db` en écriture, hormis l'`init_db` idempotent déclenché par l'import de `web.py` (voir finding dédié).

---

## Detailed Findings

### [Blocker] Les indices des manches verrouillées et non démarrées sont livrés au navigateur
- **Location:** [web.py:89-157](../../source/pere_noel_fremo/web.py#L89-L157), [espace_lutin.html:348](../../source/pere_noel_fremo/templates/espace_lutin.html#L348)
- **Category:** Security
- **Description:** `GET /lutin/{token}?manche=N` accepte n'importe quelle manche existante, y compris une manche dont `unlock_at` est dans le futur, et sérialise ses indices en base64 dans `const OBF_CLUES`. Aucun contrôle de déverrouillage, de Confirmation de présence ou de démarrage du chronomètre n'est fait sur ce chemin (ces contrôles n'existent que dans `_get_lutin_and_manche_or_raise`, pour les routes POST). Un Lutin peut ainsi résoudre hors chrono les 15 grilles à l'avance, puis enchaîner `start`/`solve` en une seconde. Le problème se pose aussi pour la manche active : les indices sont dans la source HTML avant le clic sur « Démarrer ». Cela contredit [ADR 0006 §2](../adr/0006-defi-luge-carte-a-gratter-et-tableau-des-scores.md) (« la grille et les indices restent rigoureusement masqués ») et la Couche A/B de [ADR 0007 §3](../adr/0007-championnat-multi-manches-defi-du-lutin.md).
- **Evidence:** script de reproduction (base temporaire, Lutin sans Confirmation de présence) :
  ```
  manche15 locked? True | leaked clue: Basile joue de la Clochette.
  ```
- **Recommendation:** Ne jamais rendre les indices dans la page. Les servir via un `POST /api/lutin/{token}/defi/{manche_id}/start` qui vérifie déverrouillage et présence, et qui ne renvoie les indices qu'une fois `started_at` posé. Rejeter `?manche=N` vers une manche verrouillée, ou n'en afficher que les métadonnées (titre, date). Ajouter un test `test_web` : manche verrouillée → aucun indice dans la réponse.

### [Blocker] Collision de Pseudo de lutin dans l'effectif réel : le classement fusionne deux Lutins
- **Location:** [defi.py:68-76](../../source/pere_noel_fremo/defi.py#L68-L76), [defi.py:133-134](../../source/pere_noel_fremo/defi.py#L133-L134), [web.py:143-150](../../source/pere_noel_fremo/web.py#L143-L150)
- **Category:** Quality (intégrité des données)
- **Description:** Le pseudo est tiré dans un espace de 12 × 15 = 180 combinaisons. Avec 26 Lutins, la probabilité d'au moins une collision dépasse 80 %. `calculate_championship_standings` agrège les scores dans un `dict` **indexé par pseudo**, et `my_standing` est retrouvé par pseudo. Deux Lutins de même pseudo partagent donc une ligne : leurs points s'additionnent et chacun voit le rang de l'autre. C'est le classement qui décide qui ouvre son cadeau en premier.
- **Evidence:**
  ```
  ids de res/2025/data_in.yml (26) → {'Marmotte Polaire': 2}
  [('jdenis', 'Marmotte Polaire'), ('mdenis', 'Marmotte Polaire')]
  # chacun résout la manche 1 :
  standings: [('Marmotte Polaire', 14, 2), ...]   # 10+… points fusionnés, 2 manches pour une seule ligne
  ```
- **Recommendation:** Indexer le classement par `lutin_id` (le champ est déjà dans `scores_defi`), en n'exposant que le pseudo à l'affichage. Attribuer les pseudos par tirage **sans remise** à l'échelle de l'édition, persisté en base, plutôt que par hachage indépendant. Ajouter un test d'unicité des pseudos sur l'effectif réel.

### [Major] Validation de grille illimitée : la manche se force en ~1 s
- **Location:** [web.py:265-313](../../source/pere_noel_fremo/web.py#L265-L313)
- **Category:** Security (équité du Défi)
- **Description:** `_handle_solve_defi` renvoie 400 sur une solution fausse sans rien consigner, puis accepte une nouvelle soumission. Toutes les grilles de `res/2026/grilles/` font 3 × 3 × 3, soit 3! × 3! = 36 solutions possibles. Un script les essaie toutes juste après `start` et obtient un temps quasi nul. ADR 0006 autorise les soumissions sans « pénalité arbitraire », mais [ADR 0007 §3](../adr/0007-championnat-multi-manches-defi-du-lutin.md) a pour objectif explicite un chronomètre équitable.
- **Evidence:**
  ```
  brute-force solved after 17 tries: {'ok': True, 'manche_id': 1, 'solved': True, 'time_seconds': 1.1, ...}
  ```
- **Recommendation:** Compter les soumissions dans `scores_defi` (`attempts INTEGER`) et soit plafonner (ex. 3), soit ajouter une pénalité de temps par essai faux, soit imposer un délai minimal entre soumissions. Enregistrer les tentatives pour audit.

### [Major] Échec d'envoi Gmail compté comme succès et horodaté `sent_at`
- **Location:** [helper.py:138-149](../../source/pere_noel_fremo/helper.py#L138-L149), [annonce.py:212-222](../../source/pere_noel_fremo/annonce.py#L212-L222)
- **Category:** Quality (gestion d'erreurs)
- **Description:** `gmail_send_email` capture `Exception`, journalise et renvoie `None`. `send_annonces` ne teste pas ce retour : il appelle `mark_token_sent` et incrémente `sent_count`. Son propre `except` est donc du code mort. Un jeton OAuth révoqué, un quota Gmail dépassé, ou `run_local_server` impossible sur le Homelab sans navigateur (ADR 0009 §5) donnent tous « Campagne d'Annonce terminée : N courriels envoyés ».
- **Evidence:**
  ```
  An error occurred: token revoked
  stats: {'total': 1, 'sent': 1, ...} | sent_at: 2026-10-13 20:55:09
  ```
- **Recommendation:** Faire remonter l'exception depuis `gmail_send_email`, ou renvoyer un résultat explicite que `send_annonces` vérifie. Compter les échecs séparément (`"echecs"`) et ne poser `sent_at` qu'après succès. Ajouter un test avec `build` mocké qui lève.

### [Major] Pseudos de lutin calculables par tous (pas de sel, contrairement à l'ADR)
- **Location:** [defi.py:70](../../source/pere_noel_fremo/defi.py#L70)
- **Category:** Security & Privacy
- **Description:** La graine `f"fremo_luge:{year}:{lutin_id}"` est publique (dans le code) et les identifiants suivent la convention initiale + nom (`jdenis`, `aboinet`…). N'importe quel participant peut calculer le pseudo de tous les autres et lever l'anonymat du Tableau des scores public `/scores`, ce que l'ADR veut justement éviter ([ADR 0006 §4](../adr/0006-defi-luge-carte-a-gratter-et-tableau-des-scores.md#L30) : « hachage … **avec sel cryptographique** » ; [GLOSSARY.md](../../GLOSSARY.md) : « préserver le secret de l'identité du vainqueur »).
- **Evidence:** pendant la revue, le pseudo de chaque Lutin a été calculé à partir de son seul identifiant (voir finding sur la collision).
- **Recommendation:** Corrigé en même temps que la collision : pseudo tiré aléatoirement à l'ouverture de l'édition et persisté. À défaut, HMAC avec un secret lu depuis `secure_data.yml`.

### [Minor] Le chronomètre a une résolution d'une seconde, pas d'un dixième
- **Location:** [database.py:555](../../source/pere_noel_fremo/database.py#L555), [web.py:294](../../source/pere_noel_fremo/web.py#L294)
- **Category:** Quality
- **Description:** `started_at = CURRENT_TIMESTAMP` est tronqué à la seconde et relu avec `"%Y-%m-%d %H:%M:%S"`. Le temps affiché « au dixième » a donc jusqu'à 1 s d'erreur, et deux Lutins à 30 s peuvent être départagés à tort. Cela contredit [ADR 0006 §3](../adr/0006-defi-luge-carte-a-gratter-et-tableau-des-scores.md#L23).
- **Recommendation:** Stocker `started_at` en UTC ISO avec millisecondes (`strftime('%Y-%m-%d %H:%M:%f','now')` ou horodatage Python passé en paramètre), et injecter l'horloge pour pouvoir la tester.

### [Minor] Lignes `scores_defi` créées sur un GET, Lutins non participants dans le classement
- **Location:** [web.py:108-121](../../source/pere_noel_fremo/web.py#L108-L121), [database.py:510-530](../../source/pere_noel_fremo/database.py#L510-L530)
- **Category:** Architecture
- **Description:** Chaque affichage de l'Espace Lutin fait un `INSERT OR IGNORE` dans `scores_defi` pour les 15 manches, même sans Confirmation de présence et même si le Lutin a décliné. `get_scores_classement` et `calculate_championship_standings` lisent toutes ces lignes. Un Lutin qui a seulement ouvert son lien apparaît donc à 0 point au Tableau des scores public. C'est aussi une mutation d'état sur un GET.
- **Recommendation:** Lire sans créer (`SELECT` → `{}` par défaut) sur le GET, ne créer la ligne qu'au `start`, et filtrer le classement sur `started_at IS NOT NULL`.

### [Minor] `import pere_noel_fremo.web` initialise la base de production
- **Location:** [web.py:39-42](../../source/pere_noel_fremo/web.py#L39-L42), [web.py:400](../../source/pere_noel_fremo/web.py#L400)
- **Category:** Architecture (testabilité)
- **Description:** `app = create_app()` au niveau module lance `init_db(res/fremo.db)`, avec création de dossier, `executescript` et migration éventuelle, à chaque import, y compris pendant `pytest` ([test_web.py:6](../../tests/test_web.py#L6)) et la CLI `serve`, qui construit ensuite une seconde app. `init_db` renvoie en plus une connexion ouverte que `create_app` ne ferme jamais ([database.py:76-137](../../source/pere_noel_fremo/database.py#L76-L137)).
- **Recommendation:** Supprimer l'instance module, ou passer par `uvicorn --factory pere_noel_fremo.web:create_app`. Faire fermer sa connexion à `init_db` (renvoyer `None`) et adapter `import_yaml_data`.

### [Minor] Résolution de `RES_DIR` dupliquée et incohérente
- **Location:** [helper.py:25-35](../../source/pere_noel_fremo/helper.py#L25-L35), [web.py:39-41](../../source/pere_noel_fremo/web.py#L39-L41), [defi.py:10](../../source/pere_noel_fremo/defi.py#L10), [cli.py:10](../../source/pere_noel_fremo/cli.py#L10), [email_tossing.py:18](../../source/pere_noel_fremo/email_tossing.py#L18), [email_annonce.py:13](../../source/pere_noel_fremo/email_annonce.py#L13)
- **Category:** Architecture
- **Description:** Quatre copies de la même expression `FREMO_RES_DIR`/`/app/res`/`PROJECT_ROOT`, et `resolve_res_dir()` existe déjà dans `helper`. Les deux modules legacy figent `PROJECT_ROOT / "res"` et ignorent `FREMO_RES_DIR`, alors que le commit `1247b29` annonce un support « across all modules ». Dans l'image Docker, `PROJECT_ROOT` pointe vers `site-packages/..`.
- **Recommendation:** Un seul module `config.py` (ou `helper.resolve_res_dir`) importé partout.

### [Minor] Deux pipelines de tirage et d'Annonce coexistent
- **Location:** [email_tossing.py](../../source/pere_noel_fremo/email_tossing.py), [email_annonce.py](../../source/pere_noel_fremo/email_annonce.py), [pyproject.toml:20-23](../../pyproject.toml#L20-L23)
- **Category:** Quality (code mort / redondance)
- **Description:** `pere-noel-tossing` et `pere-noel-annonce` (YAML, `DEFAULT_YEAR = 2025`, envoi du Bénéficiaire en clair par courriel) restent des points d'entrée publiés, en parallèle de `pere-noel tirage|annonce` (SQLite, Admin aveugle). L'algorithme de tirage existe en deux copies ([tirage.py:63-138](../../source/pere_noel_fremo/tirage.py#L63-L138) et `email_tossing.py`). Lancer le mauvais script par erreur casserait l'Admin aveugle de l'ADR 0005.
- **Recommendation:** Déprécier ou supprimer les entrées legacy, ou les transformer en simple adaptateur YAML → `tirage.solve_tirage`.

### [Minor] Logique de migration ponctuelle avec identifiants nominatifs dans le module de production
- **Location:** [database.py:743-758](../../source/pere_noel_fremo/database.py#L743-L758), [database.py:801-808](../../source/pere_noel_fremo/database.py#L801-L808)
- **Category:** Quality
- **Description:** `compute_historical_attributions_map` contient des corrections au cas par cas (`jdenis`, `cmouret`, `fleduff`, `schouteau`, `tmoro`, `scarrea`). `backfill_historical_attributions(purge_2026=True)` **supprime par défaut** les attributions 2026 et repasse l'édition en `announced`. Relancer ce backfill après le tirage 2026 l'effacerait.
- **Recommendation:** Déplacer ce code dans un script de migration daté (`scripts/migrations/2026_10_backfill.py`) et passer `purge_2026` à `False` par défaut, ou exiger un drapeau explicite.

### [Minor] `save_attributions` incrémente `order_index` à chaque nouveau tirage de la même année
- **Location:** [database.py:422-434](../../source/pere_noel_fremo/database.py#L422-L434)
- **Category:** Quality
- **Description:** `MAX(order_index)+1` est calculé **avant** le `DELETE` de la ligne de l'année courante. Chaque re-tirage décale donc l'index et laisse des trous. C'est sans effet sur les contraintes, mais l'ordre de l'Historique en souffre.
- **Recommendation:** Faire le `DELETE` avant de calculer l'index.

### [Minor] Exposition réseau et conteneur exécuté en root
- **Location:** [Dockerfile:24](../../Dockerfile#L24), [docker-compose.yml:9](../../docker-compose.yml#L9)
- **Category:** Security
- **Description:** `ports: "8000:8000"` publie le service sur toutes les interfaces de l'hôte (LAN compris) en plus de Funnel. L'image n'a pas de `USER`. Les journaux d'accès uvicorn contiennent le chemin `/lutin/{token}`, donc des Liens magiques en clair dans `docker logs`.
- **Recommendation:** `"127.0.0.1:8000:8000"` (Funnel passe par le loopback), `USER` non privilégié, et `--no-access-log` ou un filtre qui masque le jeton.

### [Minor] Courriels HTML avec une alternative texte factice
- **Location:** [helper.py:113-114](../../source/pere_noel_fremo/helper.py#L113-L114)
- **Category:** Quality
- **Description:** La partie `text/plain` vaut toujours « This is the alternative plain text message. ». Un client en texte seul n'affiche donc pas le Lien magique, et le score anti-spam en pâtit. Le correctif non commité sur la branche `img_path` est bon : sans image, il ne référence plus `cid:image1`.
- **Recommendation:** Générer une version texte minimale (salutation + URL du Lien magique) dans `create_message`.

### [Minor] CHANGELOG et version en retard sur le code livré
- **Location:** [CHANGELOG.md:8](../../CHANGELOG.md#L8), [pyproject.toml:7](../../pyproject.toml#L7)
- **Category:** Release
- **Description:** La dernière entrée (1.5.0, 2026-10-11) ne mentionne ni l'Espace Lutin, ni SQLite, ni la CLI `pere-noel`, ni le Défi, ni Docker (ADR 0005 à 0009, tickets #13 à #23). Il n'y a pas de section `[Unreleased]`. Le tag `2024_1.5.0` existe déjà pour un autre contenu que celui que décrit le CHANGELOG pour 1.5.0.
- **Recommendation:** Ajouter `[Unreleased]` maintenant, puis publier en 2.0.0 (changement d'architecture) avec un tag `2026_2.0.0`.

### [Minor] Dates incohérentes dans l'ADR 0007 et dérive de vocabulaire
- **Location:** [ADR 0007:4,11,21](../adr/0007-championnat-multi-manches-defi-du-lutin.md#L11), [manche_1.yml:3](../../res/2026/grilles/manche_1.yml#L3), [GLOSSARY.md:78](../../GLOSSARY.md#L78)
- **Category:** Release
- **Description:** L'ADR fixe le coup d'envoi au « vendredi 16 octobre **2027** » et le réveillon au « dimanche 5 décembre 2027 ». Les grilles commencent le **2026**-10-12 (un lundi) et finissent le 2026-12-04. Le glossaire range « Pseudo de lugeur » dans _Avoid_, mais le code l'utilise 30 fois (`pseudo_lugeur`, colonne SQL, `generate_pseudo_lugeur`). Les statuts d'édition (`draft/announced/drawn/revealed`) sont des chaînes libres, sans `CHECK`, et `revealed` n'est jamais écrit.
- **Recommendation:** Corriger les dates de l'ADR. Renommer progressivement en `pseudo_lutin`, l'alias existe déjà. Ajouter `CHECK (status IN (...))` ou un `Enum`.

### [Minor] Hygiène de l'outillage
- **Location:** [.gitignore](../../.gitignore), [.pre-commit-config.yaml:26](../../.pre-commit-config.yaml#L26), [requirements.txt](../../requirements.txt)
- **Category:** Release
- **Description:** `scratch/`, qui contient `test_fremo.db` et des scripts OAuth, n'est pas dans `.gitignore` (il l'est dans `.dockerignore`) et fait échouer `ruff check .`. `uv.lock` n'est pas suivi. `requirements.txt` n'inclut ni `fastapi`, `uvicorn` ou `jinja2`, ni `httpx` (requis par `TestClient`). Le hook mypy n'a pas `fastapi`/`pydantic` dans ses `additional_dependencies` et vérifie donc `web.py` avec des `Any`. Le hook local pytest pointe sur `.venv/Scripts/pytest.exe`, un chemin propre à Windows.
- **Recommendation:** Ajouter `scratch/` au `.gitignore`. Choisir une source de vérité (`pyproject` + `[project.optional-dependencies] dev` + `uv.lock` suivi). Compléter les dépendances du hook mypy.

### [Observation] Accès SQLite synchrones dans des handlers `async def`
- **Location:** [web.py:89-190](../../source/pere_noel_fremo/web.py#L89-L190)
- **Category:** Performance
- **Description:** Chaque handler `async` fait des I/O SQLite et YAML bloquants, ce qui bloque la boucle d'événements. Un affichage de l'Espace Lutin coûte environ 35 connexions SQLite (15 `get_or_create` + 15 `get_scores_classement` + divers) et environ 30 lectures YAML (`get_all_manches` appelé deux fois). Pour une trentaine de Lutins, c'est négligeable.
- **Recommendation:** Déclarer les handlers en `def`, pour que FastAPI les exécute dans son threadpool, et mettre en cache les grilles par édition.

### [Observation] Solutions des grilles versionnées dans Git
- **Location:** [res/2026/grilles/](../../res/2026/grilles/manche_1.yml)
- **Category:** Security
- **Description:** Les 15 solutions sont commitées. Si un Lutin a accès au dépôt Forgejo, elles sont publiques. Ce n'est un risque que selon la visibilité du dépôt.
- **Recommendation:** Déplacer les grilles hors du dépôt (comme `secure_data.yml`) ou chiffrer le champ `solution`.

---

## Suivi de la revue du 2026-10-11

| Finding précédent | État |
|---|---|
| Constantes année/absents en dur | 🟡 Partiel : `--year`/`--absent` existent, mais `2026` reste figé en défaut ([cli.py:37](../../source/pere_noel_fremo/cli.py#L37)), dans `get_latest_edition_year`, `DEFAULT_GRILLE_2026` et `purge_2026` |
| Journaux à la racine | ✅ Corrigé : `LOGS_DIR` ([helper.py:36](../../source/pere_noel_fremo/helper.py#L36)), `logs/` ignoré |
| mypy `no-any-return` sur `load_credentials` | ✅ Corrigé : `cast` ([helper.py:99](../../source/pere_noel_fremo/helper.py#L99)), mypy propre |
| Validation de schéma YAML | ✅ Corrigé pour le legacy (`validate_lutins_data`) ; intégrité référentielle dans `import_yaml_data` |
| Pas de `--dry-run` | ✅ Corrigé sur `annonce` et `tirage` |
| Pas de CHANGELOG | ✅ Créé, mais en retard (voir ci-dessus) |
| Tirage Monte-Carlo vs couplage biparti | Inchangé (Observation toujours valable) |

---

## ⏸️ Non vérifié : nécessite l'environnement d'exécution réel

- **Envoi Gmail réel et flux OAuth sur le Homelab.** Procédure : `pere-noel annonce --lutin <id> --override-email <adresse de test>` depuis le conteneur, puis vérifier la réception et `tokens.sent_at`. Vérifier aussi que `run_local_server` n'est pas déclenché sans navigateur.
- **Exposition Tailscale Funnel.** Procédure : depuis un réseau externe, `curl -I https://homelab.tail7d8b91.ts.net:10000/scores`, et depuis le LAN `curl http://<ip-homelab>:8000/` pour constater l'exposition directe.
- **Efficacité anti-OCR des Couches A à C de l'ADR 0007 sur mobile.** Elle dépend du rendu Canvas et du comportement `onblur` sur iOS/Android. Elle est de toute façon contournée par la fuite des indices décrite plus haut.

---

## Ruled-Out Items (Verified Clean)

- **Injection SQL** : toutes les requêtes de [database.py](../../source/pere_noel_fremo/database.py) et [tokens.py](../../source/pere_noel_fremo/tokens.py) utilisent des paramètres `?`. Aucune interpolation f-string dans du SQL (relu ligne à ligne).
- **Génération des Liens magiques** : `secrets.token_urlsafe(16)` (128 bits, [tokens.py:9](../../source/pere_noel_fremo/tokens.py#L9)). Une recherche exhaustive est irréaliste malgré l'absence de limitation de débit.
- **Contrôles d'accès des routes POST** : `presence` refuse après tirage (403), `start/solve/abandon` exigent présence et déverrouillage (`_get_lutin_and_manche_or_raise`), `beneficiaire` exige `drawn|revealed`. Un jeton inconnu donne 404 partout.
- **XSS** : Jinja2 autoescape actif (`Jinja2Templates`). Les données injectées en JS passent par `| tojson`, et le jeton est alphanumérique url-safe.
- **Secrets dans Git** : `git ls-files` ne contient ni `secure_data.yml`, ni `token.json`, ni `code_secret_client*.json`, ni `*.db`. Ils existent localement dans `res/` et sont couverts par `.gitignore` (`**/secure_data.yml`, `token.json`, `res/*.json`, `*.db`).
- **Admin aveugle** : `TirageResult.get_masked_summary` et le `logger.info` de `run_tirage` n'impriment aucune paire ([tirage.py:27-60](../../source/pere_noel_fremo/tirage.py#L27-L60), [tirage.py:174](../../source/pere_noel_fremo/tirage.py#L174)).
- **Invariants du tirage** : auto-cadeau, exclusions, historique hors année courante (`exclude_year`) et bijection, vérifiés dans `solve_tirage` et revérifiés par `audit_tirage`, avec tests dans `test_tirage.py`.
- **Gestion des ressources** : chaque fonction de `database.py` et `tokens.py` ferme sa connexion dans un `finally`, sauf `init_db` (voir finding). Les fichiers sont ouverts avec `with`.
- **Arguments par défaut mutables** : aucun `def f(x=[])` dans `source/` (les `default=[]` d'`argparse` ne sont pas concernés).
- **Tests fragiles** : aucun `time.sleep` dans `tests/`. L'horloge est injectée (`now=`) dans `defi`.
- **Validation d'entrée HTTP** : corps validés par Pydantic (`PresenceRequest`, `GrilleSolveRequest`). `manche_id` est typé `int`.
- **Layout de package (ADR 0003)** : `source/pere_noel_fremo/` avec `package-data` pour les templates et le CSS, entrée `pere-noel` opérationnelle (`test_cli.py`).
