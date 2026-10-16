# Project Review: Le Père Noël de la Frémo (Project)

**Date:** 2026-10-16
**Commit:** b633ab6 (arbre de travail propre, branche `develop`, 19 commits après le tag `2026_2.0.1`)
**Stack Profile:** Python (3.10+, FastAPI + SQLite)
**Reviewer:** AI Pair Programmer

## Executive Summary

Depuis la revue post-release du 15 octobre ([2026-10-15-post-release-review.md](2026-10-15-post-release-review.md)), les cinq refactorisations de la série #57 à #63 ont transformé l'architecture. Le statut d'une Édition a désormais un seul propriétaire ([edition.py](../../source/pere_noel_fremo/edition.py)) avec une table de transitions explicite. Le Parcours de manche ([parcours.py](../../source/pere_noel_fremo/parcours.py)) enchaîne gardes et écriture dans une seule transaction `BEGIN IMMEDIATE`. L'Annonce et la Révélation partagent une seule boucle d'envoi derrière le port `Expediteur` ([campagne.py](../../source/pere_noel_fremo/campagne.py)). Les 14 constats Minor de la revue précédente sont tous traités : transaction imbriquée du pseudo, audit avant écriture, code mort, couverture des rejets de grille, journalisation des manches illisibles, échappement HTML, `token.json` en `0600`, handlers synchrones, verrou `uv.lock`, CI Forgejo. `ruff`, `ruff format`, `mypy`, `bandit` et `uv lock --check` ne signalent rien ; 369 tests passent et la couverture lignes+branches atteint 93,54 % (seuil 92 %).

Un constat **Major** subsiste, vérifié par script. Un envoi de Révélation avec `--override-email` mais sans `--lutin` (le cas d'usage « tester le courriel sur ma propre adresse ») fait passer l'Édition à `revealed` et marque tous les Liens magiques comme envoyés, alors qu'aucun Lutin n'a rien reçu. `revealed` est un état terminal : le `--force-retirage` devient impossible et le suivi `sent_at` est faux. L'Annonce a le même défaut (`draft` → `announced`).

Les autres constats sont mineurs. La Confirmation de présence n'est pas atomique avec le scellement du tirage. Le Défi du lutin ne se ferme jamais après le Repas de Noël, contrairement à l'ADR-0007. La CLI se rabat en silence sur les fichiers de 2025. Les journaux applicatifs INFO ne sont émis nulle part (`configure_logger` n'est jamais appelée). Il reste aussi deux duplications : la garde d'accès des indices et les formateurs de courriel.

---

## Scorecard

| Dimension | Rating | Findings (B/M/m/O) |
|---|---|---|
| Architecture & System Structure | ⚠️ | 0 Blocker, 1 Major, 2 Minor, 2 Observation |
| Code Quality & Maintainability | ✅ | 0 Blocker, 0 Major, 5 Minor, 1 Observation |
| Security & Privacy | ✅ | 0 Blocker, 0 Major, 0 Minor, 2 Observation |
| Performance & Efficiency | ✅ | 0 Blocker, 0 Major, 0 Minor, 2 Observation |
| Release Readiness & Governance | ✅ | 0 Blocker, 0 Major, 2 Minor, 0 Observation |

---

## Résultats des outils de vérification

| Commande | Résultat |
|---|---|
| `uv run --frozen ruff check .` | ✅ All checks passed! |
| `uv run --frozen ruff format --check .` | ✅ 65 files already formatted |
| `uv run --frozen mypy source tests` | ✅ Success: no issues found in 37 source files |
| `uv run --frozen bandit -c pyproject.toml -r source -q` | ✅ aucun problème (code retour 0) |
| `uv lock --check` | ✅ Resolved 79 packages |
| `uv run --frozen pytest -q` | ✅ 369 passed, 2 skipped (modes POSIX sous Windows, [test_helper.py:201](../../tests/test_helper.py#L201)) ; couverture lignes+branches **93,54 %** (seuil 92 %). Plus faibles : `helper.py` 86 %, `web.py` 88 % |
| `uv pip list --outdated` | Correctifs mineurs uniquement, outillage de dev (ruff 0.17.0→0.17.1, pre-commit 4.6.2→4.7.0, pluggy, filelock…) ; aucune dépendance d'exécution en retard |
| Script `override_repro.py` (base temporaire, voir constat Major) | `destinataires ['test@exemple.fr']`, `statut revealed`, `tokens sent_at non nuls 2` |
| Script `docs_probe.py` (`TestClient` sur `create_app`) | `/docs 200`, `/openapi.json 200`, `/redoc 200`, 14 routes décrites |
| `dictConfig(uvicorn LOGGING_CONFIG)` puis `logger.info/warning` sur `pere_noel_fremo.campagne` | racine sans handler (`[]`, niveau WARNING) : seul le WARNING s'affiche, l'INFO est perdu |

⏸️ **Non vérifié, nécessite l'environnement d'exécution réel :** build et démarrage de l'image Docker, exposition Tailscale Funnel, envoi réel Gmail (jeton OAuth), rendu des courriels dans Outlook/Gmail/Apple Mail (ADR-0010), comportement des couches anti-triche (Canvas, rideau `blur`) sur mobile. Procédure : `docker compose build && docker compose up -d`, `curl -I https://homelab.tail7d8b91.ts.net:10000/scores`, puis `pere-noel annonce --lutin <id> --override-email <adresse de test>` **après correction du constat Major** (sinon cet envoi ferait avancer l'Édition), et ouverture du Lien magique reçu sur un téléphone.

---

## Detailed Findings

### [Major] `--override-email` sans `--lutin` fait avancer l'Édition et marque tous les jetons envoyés
- **Location:** [revelation.py:110-112](../../source/pere_noel_fremo/revelation.py#L110), [annonce.py:110-111](../../source/pere_noel_fremo/annonce.py#L110), [campagne.py:164-176](../../source/pere_noel_fremo/campagne.py#L164)
- **Category:** Architecture
- **Description:** L'aide de la CLI présente `--override-email` comme une redirection « vers cette adresse de test » ([cli.py:274-279](../../source/pere_noel_fremo/cli.py#L274)). Mais `send_revelations` ne considère comme « ciblé » qu'un envoi avec `target_lutins` : sans `--lutin`, chaque Révélation part vers l'adresse de test, puis l'Édition passe de `drawn` à `revealed`. En même temps, `envoyer_campagne` appelle `mark_token_sent` pour chaque Lutin. Résultat : aucun Lutin n'a reçu son courriel, la base affirme le contraire, et l'Édition est dans un état terminal. `revealed → drawn` est interdit ([edition.py:30-37](../../source/pere_noel_fremo/edition.py#L30)), donc un `--force-retirage` est refusé. Le vrai envoi reste possible (`est_scellee(revealed)` est vrai), ce qui rend l'incident récupérable, d'où Major et non Blocker. L'Annonce a le même défaut : `draft → announced` après un envoi de test.
- **Evidence:** script `override_repro.py` (fixture `setup_sample_db` de [test_revelation.py:60](../../tests/test_revelation.py#L60), deux Lutins confirmés, tirage scellé, `send_revelations(..., recipient_override="test@exemple.fr")`) :
  ```
  stats {'total': 2, 'sent': 2, 'sans_email': 0, 'echecs': 0}
  destinataires ['test@exemple.fr']
  statut revealed
  tokens sent_at non nuls 2
  ```
  Le seul test de l'override combiné à un ciblage ([test_revelation.py:195](../../tests/test_revelation.py#L195)) passe `target_lutins`, ce qui masque le cas.
- **Recommendation:** Traiter un envoi redirigé comme une simulation d'état. Dans `envoyer_campagne`, ne pas appeler `mark_token_sent` quand `override_email` est fourni. Dans `send_revelations` et `send_annonces`, ne pas appeler `avancer_edition` si `recipient_override` ou `target_lutins` est fourni. Ajouter un test par campagne : override sans cible → statut inchangé et `sent_at` nul.

### [Minor] La Confirmation de présence n'est pas atomique avec le scellement du tirage
- **Location:** [web.py:273-279](../../source/pere_noel_fremo/web.py#L273), [database.py:518](../../source/pere_noel_fremo/database.py#L518), [tirage.py:178](../../source/pere_noel_fremo/tirage.py#L178) et [tirage.py:221](../../source/pere_noel_fremo/tirage.py#L221)
- **Category:** Architecture
- **Description:** `post_presence` lit le statut (une connexion), puis `set_lutin_presence` écrit dans une autre transaction, sans relire le statut. De son côté, `run_tirage` lit les Lutins confirmés, résout, puis `save_attributions` scelle dans une nouvelle transaction ([database.py:617-642](../../source/pere_noel_fremo/database.py#L617)) sans vérifier que l'ensemble confirmé est inchangé. Une présence modifiée dans l'intervalle donne un tirage scellé qui ne correspond plus aux présences : un Lutin qui se désiste après le scellement reste Donneur, ou un Lutin confirmé à la dernière seconde est exclu. Après coup, `audit-tirage` signalerait l'incohérence, mais la Révélation ([revelation.py:94](../../source/pere_noel_fremo/revelation.py#L94)) s'appuie sur les présences du moment. La fenêtre est de quelques millisecondes et le tirage est une opération d'administrateur unique, d'où la sévérité Minor.
- **Evidence:** lecture du code. Aucune des deux écritures n'utilise `begin_immediate` avec une relecture de la garde. Le schéma de `parcours` (gardes et écriture dans une seule transaction) n'est pas appliqué ici.
- **Recommendation:** Déplacer la garde dans une fonction `presence.confirmer(conn, …)` qui exécute `BEGIN IMMEDIATE`, relit `edition.statut` puis écrit. Dans `save_attributions`, relire l'ensemble confirmé dans la transaction de scellement et lever une erreur s'il diffère des donneurs de `pairs`.

### [Minor] Le Défi du lutin ne se ferme jamais après le Repas de Noël
- **Location:** [parcours.py:171-185](../../source/pere_noel_fremo/parcours.py#L171), [parcours.py:262](../../source/pere_noel_fremo/parcours.py#L262)
- **Category:** Architecture
- **Description:** Selon l'[ADR-0007 §2](../../docs/adr/0007-championnat-multi-manches-defi-du-lutin.md), le rattrapage est ouvert « jusqu'au réveillon du samedi 5 décembre 2026 », et le classement détermine qui ouvre son cadeau en premier lors du Repas de Noël. `_garde_acces` ne vérifie que la présence, l'existence et `unlock_at` : aucune borne de fin. `date_repas` existe en base ([database.py:548](../../source/pere_noel_fremo/database.py#L548)), mais aucun module du Défi ne la lit. Après le Repas, des démarrages et des Soumissions continuent de modifier le Tableau des scores public.
- **Evidence:** `grep date_repas` dans `parcours.py` et `defi.py` : aucune occurrence.
- **Recommendation:** Ajouter une garde `DEFI_CLOS` dans `_garde_acces` (fin du jour de `date_repas`, heure de Paris), avec une traduction HTTP 403 dans `_refus_parcours`. Ou bien amender l'ADR si la clôture doit rester manuelle.

### [Minor] La CLI se rabat en silence sur les fichiers de 2025
- **Location:** [cli.py:326-328](../../source/pere_noel_fremo/cli.py#L326), [cli.py:363-364](../../source/pere_noel_fremo/cli.py#L363)
- **Category:** Quality
- **Description:** Quand `res/{year}/data_in.yml` ou `res/{year}/annonce.txt` est absent, `init-db` importe `res/2025/data_in.yml` et `annonce` utilise `res/2025/annonce.txt`, sans aucun message. Pour une Édition 2027 préparée à moitié, `init-db` réactive donc les Lutins de 2025, et l'Annonce enverrait l'ancien gabarit « Snow Rider 3D » (`diff res/2025/annonce.txt res/2026/annonce.txt` montre deux contenus sans rapport). `revelation` n'a pas ce repli et retombe sur le gabarit intégré, ce qui est plus sûr.
- **Recommendation:** Supprimer les deux replis sur 2025. Utiliser le gabarit intégré de `gabarits.py` pour l'Annonce (comme pour la Révélation), et sortir en erreur explicite pour `init-db` quand le `data_in.yml` de l'année manque.

### [Minor] `configure_logger` n'est jamais appelée : les journaux applicatifs INFO sont perdus
- **Location:** [helper.py:39](../../source/pere_noel_fremo/helper.py#L39), [cli.py:422-435](../../source/pere_noel_fremo/cli.py#L422)
- **Category:** Release
- **Description:** Seul [test_helper.py:253](../../tests/test_helper.py#L253) appelle `configure_logger`. Ni `main` ni `handle_serve` ne configure la racine, et la configuration uvicorn ne touche que les journaux `uvicorn.*`. Les messages INFO (`Sent to a***@…`, succès du tirage en Admin aveugle) ne sont donc émis nulle part, et rien n'est écrit dans `logs/`. Les WARNING et ERROR n'atteignent stderr que via le `lastResort` de la bibliothèque standard. L'[ADR-0005 §4](../../docs/adr/0005-espace-lutin-fastapi-sqlite-et-admin-aveugle.md) compte pourtant sur des « journaux détaillés » auditables.
- **Evidence:** `dictConfig(uvicorn.config.LOGGING_CONFIG)` → `root handlers: [] level WARNING` ; seul `WARNING visible ?` s'affiche.
- **Recommendation:** Appeler `configure_logger("pere_noel.log")` au début de `main()`, et vérifier que `TokenMaskingFilter` et `mask_email` couvrent tout ce qui part dans ce fichier.

### [Minor] La garde d'accès des indices duplique celle du Parcours
- **Location:** [web.py:282-308](../../source/pere_noel_fremo/web.py#L282), [web.py:367-385](../../source/pere_noel_fremo/web.py#L367)
- **Category:** Quality
- **Description:** Après #58 et #59, la route des indices est la seule qui porte encore ses gardes dans la couche HTTP. `_get_lutin_and_manche_or_raise` réécrit présence, existence et déverrouillage (logique de `parcours._garde_acces`) avec des messages copiés de `_refus_parcours`, puis la route relit `get_score_defi` hors transaction pour déterminer « essai en cours », ce que `parcours.statut_score` sait déjà faire. Les branches de refus de cette fonction ne sont pas couvertes (lignes 285, 292, 300 et 303 dans le rapport de couverture).
- **Recommendation:** Ajouter `parcours.indices(db_path, lutin_id, year, manche, now) -> ResultatParcours` (refus `NON_DEMARRE` / `DEJA_TERMINEE`), faire passer la route par `_refus_parcours` et supprimer `_get_lutin_and_manche_or_raise`.

### [Minor] Formateurs d'Annonce et de Révélation dupliqués
- **Location:** [annonce.py:22-43](../../source/pere_noel_fremo/annonce.py#L22), [revelation.py:22-43](../../source/pere_noel_fremo/revelation.py#L22)
- **Category:** Quality
- **Description:** `format_annonce_body` et `format_revelation_body` font le même travail ligne pour ligne : remplacement de `{fullname}` échappé, `{lien_magique}`, `{magic_url}` et `{year}`, puis injection d'un CTA avant `</body>`. Seuls le libellé et la couleur du CTA diffèrent. #63 a unifié la boucle d'envoi mais pas le rendu, et un correctif de sécurité (#52) a déjà dû être appliqué deux fois.
- **Recommendation:** Placer dans `campagne.py` une fonction `rendre_gabarit(gabarit, nom, lien, annee, cta)` paramétrée par le libellé et la couleur du CTA, et faire de ces deux fonctions de minces appels.

### [Minor] `get_manche` laisse remonter les erreurs YAML (HTTP 500)
- **Location:** [defi.py:226-233](../../source/pere_noel_fremo/defi.py#L226)
- **Category:** Quality
- **Description:** Depuis #51, `get_all_manches` journalise puis ignore un `manche_N.yml` illisible. `get_manche` l'ouvre sans protection, et les routes `start`, `solve`, `abandon` et `indices` l'appellent directement avec l'identifiant de l'URL : un fichier mal formé produit une erreur 500 au lieu de `MANCHE_INTROUVABLE` ou `GRILLE_INVALIDE`. Les grilles sont des données d'administrateur, d'où Minor.
- **Recommendation:** Factoriser la lecture d'un fichier de manche dans `_lire_manche(file)` et l'utiliser dans les deux fonctions (journalisation WARNING, puis `None`).

### [Minor] `import_yaml_data` ne désactive jamais un Lutin retiré du `data_in.yml`
- **Location:** [database.py:370-384](../../source/pere_noel_fremo/database.py#L370)
- **Category:** Quality
- **Description:** L'import fait un upsert `is_active = 1` sur les Lutins listés, mais ne passe jamais à `0` ceux qui ont disparu du fichier. Un Lutin retiré du `data_in.yml` de l'année reste actif : il reçoit l'Annonce ([annonce.py:94](../../source/pere_noel_fremo/annonce.py#L94), `get_lutins(active_only=True)`) et figure dans l'export.
- **Recommendation:** Dans la même transaction, exécuter `UPDATE lutins SET is_active = 0 WHERE id NOT IN (…)` pour les identifiants absents du fichier, et afficher le nombre de désactivations dans le résumé de `init-db`.

### [Minor] Le compte à rebours du Repas de Noël ignore l'horloge injectée et utilise la date UTC
- **Location:** [web.py:239](../../source/pere_noel_fremo/web.py#L239), [helper.py:238-239](../../source/pere_noel_fremo/helper.py#L238)
- **Category:** Release
- **Description:** `create_app` injecte `clock`, mais `format_date_repas` est appelée sans `now` et lit `datetime.now(timezone.utc).date()`. Le `J-xx` ne peut donc pas être testé avec l'horloge de l'application. Entre minuit et 1 h (2 h en été) à Paris, il affiche aussi la veille, alors que le reste du Défi raisonne en `Europe/Paris` (#39).
- **Recommendation:** Passer `now=clock_fn().astimezone(PARIS_TZ)` à `format_date_repas`.

### [Observation] Documentation OpenAPI publique
- **Location:** [web.py:91](../../source/pere_noel_fremo/web.py#L91)
- **Category:** Security
- **Description:** `FastAPI(...)` garde `docs_url`, `redoc_url` et `openapi_url` par défaut. Derrière Tailscale Funnel, `/docs` décrit les 14 routes à n'importe qui. Aucun secret n'est exposé (les jetons sont aléatoires sur 128 bits), mais la surface d'attaque est publiée sans raison.
- **Evidence:** `docs_probe.py` → `/docs 200`, `/openapi.json 200`, `/redoc 200`.
- **Recommendation:** Passer `docs_url=None, redoc_url=None, openapi_url=None` en production (par exemple via une variable d'environnement).

### [Observation] `--dry-run` écrit en base
- **Location:** [campagne.py:158](../../source/pere_noel_fremo/campagne.py#L158), [tokens.py:24-44](../../source/pere_noel_fremo/tokens.py#L24)
- **Category:** Security
- **Description:** Une Campagne simulée crée les Liens magiques et, si besoin, la ligne `editions` en `draft`. C'est documenté dans la docstring, et c'est idempotent, mais une simulation sur une année future fait apparaître une Édition, que `annee_courante` retiendra alors comme Édition la plus récente ([edition.py:102-114](../../source/pere_noel_fremo/edition.py#L102)).
- **Recommendation:** Accepter ce comportement et le documenter dans l'aide de `--dry-run`, ou générer un jeton éphémère sans écriture en simulation.

### [Observation] Migrations rejouées à chaque démarrage, sans version de schéma
- **Location:** [database.py:149-312](../../source/pere_noel_fremo/database.py#L149), notamment [database.py:236](../../source/pere_noel_fremo/database.py#L236)
- **Category:** Architecture
- **Description:** `init_db` réexamine toute l'histoire du schéma à chaque `create_app` et à chaque import, y compris un `DELETE FROM scores_defi WHERE started_at IS NULL` et des valeurs de repli codées en dur (`'2026-01-01 00:00:00'`). C'est inoffensif aujourd'hui, mais chaque nouvelle migration alourdit une fonction de 160 lignes qui s'exécute au démarrage du serveur.
- **Recommendation:** Introduire `PRAGMA user_version` et une liste ordonnée de migrations, à n'exécuter que si la version est inférieure.

### [Observation] Pseudo de lutin stocké en double
- **Location:** [database.py:13-20](../../source/pere_noel_fremo/database.py#L13), [database.py:60-71](../../source/pere_noel_fremo/database.py#L60)
- **Category:** Architecture
- **Description:** `pseudos(year, lutin_id, pseudo)` est la source de vérité, mais `scores_defi.pseudo_lutin` en garde une copie, resynchronisée par `init_db`. Le classement lit la copie.
- **Recommendation:** À terme, joindre `pseudos` dans `get_scores_classement` et supprimer la colonne.

### [Observation] Coût d'un affichage de l'Espace Lutin
- **Location:** [web.py:148-191](../../source/pere_noel_fremo/web.py#L148), [defi.py:127-129](../../source/pere_noel_fremo/defi.py#L127)
- **Category:** Performance
- **Description:** Chaque affichage lit les 15 YAML deux fois (`get_all_manches` directement, puis dans `calculate_championship_standings`), plus `get_manche`, et ouvre environ 20 connexions SQLite (une requête de classement par manche déverrouillée). Pour 26 Lutins, c'est négligeable.
- **Recommendation:** Rien à faire pour l'instant. Si le besoin apparaît : une requête unique `WHERE year = ?` groupée en Python, et un cache des grilles indexé par `mtime`.

### [Observation] Solveur probabiliste sans retour arrière
- **Location:** [tirage.py:94-138](../../source/pere_noel_fremo/tirage.py#L94)
- **Category:** Performance
- **Description:** `solve_tirage` tire des couples au hasard (jusqu'à 500 × 2 000 pas) sans retour arrière. Il peut échouer alors qu'une solution existe, et la contrainte d'historique se resserre chaque année (déjà noté le 15 octobre). L'audit en mémoire garantit que tout résultat accepté est valide ; le seul risque est un faux « impossible ».
- **Recommendation:** Si un échec apparaît, passer à une recherche avec retour arrière (ordre aléatoire des candidats, donneurs les plus contraints d'abord).

### [Observation] Compatibilité `giver`/`gifted` et `--organizer` sans effet
- **Location:** [tirage.py:86-92](../../source/pere_noel_fremo/tirage.py#L86), [tirage.py:42-45](../../source/pere_noel_fremo/tirage.py#L42), [cli.py:443-447](../../source/pere_noel_fremo/cli.py#L443)
- **Category:** Quality
- **Description:** Le solveur accepte encore les clés anglaises `giver`/`gifted` alors que le glossaire impose Donneur/Bénéficiaire. `--organizer` ne fait qu'ajouter trois lignes fixes au résumé. Un `--cheater` sans `:` est ignoré sans message.
- **Recommendation:** Retirer l'alias anglais, signaler un `--cheater` mal formé, et documenter que `--organizer` est purement cosmétique.

---

## Ruled-Out Items (Verified Clean)

- **Constats du 15 octobre** : tous les constats Minor sont corrigés. `get_or_assign_pseudo` n'ouvre une transaction que pour sa propre connexion ([database.py:702-708](../../source/pere_noel_fremo/database.py#L702)). Audit en mémoire avant écriture ([tirage.py:199-217](../../source/pere_noel_fremo/tirage.py#L199)). Code mort supprimé (`grep` sans résultat pour `start_manche_defi`, `complete_score_defi`, `backfill_historical_attributions`). Échappement du nom dans les deux gabarits. `token.json` en `0600` ([helper.py:105-109](../../source/pere_noel_fremo/helper.py#L105)). Routes synchrones. CI Forgejo ([ci.yml](../../.forgejo/workflows/ci.yml)) qui exécute verrou, ruff, mypy, bandit et pytest sur 3.10 et 3.12.
- **Cycle de l'Édition** : transitions explicites ([edition.py:30-37](../../source/pere_noel_fremo/edition.py#L30)). `sceller` s'exécute dans la transaction de `save_attributions`, et `TransitionEditionInterdite` déclenche un rollback ([database.py:617-642](../../source/pere_noel_fremo/database.py#L617)). La contrainte `CHECK` du statut est dérivée de l'enum (`STATUTS_SQL`). `main()` résout l'année avant tous les handlers ([cli.py:585-586](../../source/pere_noel_fremo/cli.py#L585)) : pas de chemin `res/None/`.
- **Parcours et Soumission** : `demarrer`, `abandonner` et `soumettre` ouvrent une seule connexion et un seul `BEGIN IMMEDIATE`, et les gardes sont relues dans la transaction. Plafond (3) et pénalité (15 s) ne proviennent que de [defi.py:76-77](../../source/pere_noel_fremo/defi.py#L76). Une Soumission incomplète ne consomme pas d'essai ([parcours.py:289-291](../../source/pere_noel_fremo/parcours.py#L289)). Barème `RESOLUE`/`SCELLEE`/`ABANDONNEE` conforme à l'ADR-0007 ([defi.py:89-109](../../source/pere_noel_fremo/defi.py#L89)). Mapping `StatutSoumission[acces.statut.name]` vérifié : les trois statuts de refus existent dans les deux enums.
- **Fuites de solution et d'identité** : `solution` et `indices` sont retirés de chaque manche avant le rendu ([web.py:154-157](../../source/pere_noel_fremo/web.py#L154)). Les indices ne sont servis que pendant un essai en cours. `lutin_id` est retiré du Tableau des scores public ([web.py:113-114](../../source/pere_noel_fremo/web.py#L113)) et aucun gabarit ne l'affiche (`grep lutin_id templates/` sans résultat). Le Bénéficiaire n'est servi qu'après scellement ([web.py:516](../../source/pere_noel_fremo/web.py#L516)).
- **Injection et parcours de chemin** : toutes les requêtes SQL sont paramétrées (la seule interpolation, `STATUTS_SQL`, vient d'un enum). `manche_id` est typé `int` par FastAPI, donc pas de traversée dans `manche_{id}.yml`. YAML chargé uniquement par `yaml.safe_load`. Jinja2 avec auto-échappement (seuls deux `innerHTML` côté client, sur des littéraux, [espace_lutin.html:648-652](../../source/pere_noel_fremo/templates/espace_lutin.html#L648)).
- **Secrets** : `secure_data.yml`, `token.json`, `credentials.json`, `*.db` et `res/*.json` sont ignorés par git ([.gitignore](../../.gitignore)). Seul `res/secure_data.example.yml` est suivi. Jetons générés par `secrets.token_urlsafe(16)` ([tokens.py:9-11](../../source/pere_noel_fremo/tokens.py#L9)). Pseudos tirés par `secrets.choice`. Jetons masqués dans `uvicorn.access` ([web.py:45-68](../../source/pere_noel_fremo/web.py#L45)), adresses masquées dans les journaux de campagne.
- **Conteneur** : utilisateur non privilégié `lutin` (UID 1000), port lié à `127.0.0.1` ([docker-compose.yml](../../docker-compose.yml)), dépendances exportées depuis `uv.lock --frozen` ([Dockerfile](../../Dockerfile)), `uv` désinstallé de l'image : conforme à l'ADR-0009.
- **Anti-triche (ADR-0007 §3)** : indices dessinés sur Canvas (31 occurrences `canvas`/`getContext`), rideau sur `blur`/`focus` ([espace_lutin.html:428-438](../../source/pere_noel_fremo/templates/espace_lutin.html#L428)), `oncontextmenu="return false;"` et `user-select: none` ([style.css:379](../../source/pere_noel_fremo/static/style.css#L379)).
- **Ressources Python** : toutes les connexions SQLite sont fermées dans un `finally` ou par le gestionnaire `connection()`. Fichiers ouverts par `with`. Aucun argument par défaut mutable (`field(default_factory=…)` dans les dataclasses). Aucun `subprocess`. Aucun `except:` nu (les `except Exception` restants journalisent ou convertissent).
- **Glossaire** : les termes canoniques (Lutin, Donneur, Bénéficiaire, Édition, Campagne, Parcours de manche, Soumission, Pseudo de lutin, Carte à gratter) sont ceux du code. Aucune occurrence des termes proscrits « Défi de la luge », « teaser » ou « tossing » dans `source/` (`grep -niE`), hors l'alias `giver`/`gifted` noté plus haut.
- **Gouvernance** : `pyproject.toml` en 2.0.1, comme le tag `2026_2.0.1`. Les 19 commits suivants sont tous décrits dans `[Unreleased]` du [CHANGELOG.md](../../CHANGELOG.md), avec leur ticket. ADR numérotées 0001 à 0012 sans doublon. `uv lock --check` est vert.
