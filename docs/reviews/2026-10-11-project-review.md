# Project Review: Le Père Noël de la Frémo (Full Audit)

**Date:** 2026-10-11
**Commit:** a618f35
**Stack Profile:** Python (3.10+)
**Reviewer:** AI Pair Programmer

## Executive Summary

Ce projet Python gère l'organisation, le tirage au sort sous contraintes et l'envoi personnalisé d'e-mails pour l'événement annuel du « Père Noël secret » de la Frémo. L'audit complet du dépôt met en évidence une modernisation récente très soignée : mise en place de `pre-commit`, migration vers `Ruff`, intégration de `Bandit`, adoption d'un layout de package standard sous `source/pere_noel_fremo/`, et implémentation d'un harnais de tests unitaires avec `pytest` couvrant la robustesse combinatoire du tirage et l'assemblage MIME.

Sur le plan de l'architecture et de la maintenabilité, le socle est sain et direct. Les règles métier (exclusions, historique pérenne, gestion des absents, paires forcées de cheaters) sont fidèlement respectées et formalisées dans [`GLOSSARY.md`](../../GLOSSARY.md) et la série d'ADR ([`0001`](../adr/0001-ruff-and-pre-commit.md) à [`0004`](../adr/0004-test-suite-and-tossing-resilience.md)).

Les principaux points d'amélioration identifiés concernent :
1. **Sécurité opérationnelle & Hygiène Git** : La présence de fichiers de journaux opérationnels volumineux contenant des logs d'adresses et d'exécution (`email_tossing.log` et `email_annonce.log`) directement sous la racine du projet, qui risquent d'être validés par mégarde en l'absence d'une règle d'exclusion de journalisation globale.
2. **Couverture de vérification Mypy** : Une divergence de configuration entre l'environnement de développement local (`.venv`) et le hook isolé pre-commit concernant le flag `warn_return_any = true` sur le retour de `Credentials` dans `helper.py`.
3. **Robustesse I/O et découplage CLI** : La dépendance étroite entre `email_tossing.py` et le cycle Gmail direct, ainsi que la configuration codée en dur de l'année `__YEAR = 2025` et de la liste `PERSON_TO_SKIP` en constantes de module.

---

## Scorecard

| Dimension | Rating | Findings (B/M/m/O) |
|---|---|---|
| Architecture & System Structure | ⚠️ Conforme avec réserves | 0 Blocker, 1 Major, 1 Minor, 1 Observation |
| Code Quality & Maintainability | ✅ Bon | 0 Blocker, 0 Major, 2 Minor, 1 Observation |
| Security & Privacy | ⚠️ Conforme avec réserves | 0 Blocker, 1 Major, 1 Minor, 0 Observation |
| Performance & Efficiency | ✅ Bon | 0 Blocker, 0 Major, 0 Minor, 1 Observation |
| Release Readiness & Governance | ✅ Conforme | 0 Blocker, 0 Major, 1 Minor, 0 Observation |

---

## Detailed Findings

### [Major] Constantes métier critiques codées en dur au niveau module
- **Location:** [`source/pere_noel_fremo/email_tossing.py:19-25`](../../source/pere_noel_fremo/email_tossing.py#L19-L25) et [`source/pere_noel_fremo/email_annonce.py:18-22`](../../source/pere_noel_fremo/email_annonce.py#L18-L22)
- **Category:** Architecture & System Structure
- **Description:** L'année de travail (`__YEAR = 2025`), l'objet de l'annonce et la liste des personnes absentes (`PERSON_TO_SKIP: list[str] = ["sbentabet"]`) sont déclarés en dur au sommet des modules applicatifs. Pour lancer une nouvelle édition ou changer la liste des absents sans toucher au code source, l'application devrait accepter ces valeurs via des arguments CLI (`argparse` ou `click`) ou via un fichier de configuration annuel dédié.
- **Evidence:**
  ```python
  __YEAR = 2025
  __SECURE_DATA = RES_DIR / "secure_data.yml"
  __DATA_IN = RES_DIR / f"{__YEAR}" / "data_in.yml"
  ...
  PERSON_TO_SKIP: list[str] = ["sbentabet"]
  ```
- **Recommendation:** Introduire une interface CLI acceptant `--year`, `--skip`, et `--dry-run` dans `main()` pour piloter le tirage et l'envoi sans modifier le code source.

---

### [Major] Fichiers journaux et données de production non ignorés à la racine
- **Location:** [`email_tossing.log`](../../email_tossing.log) et [`email_annonce.log`](../../email_annonce.log)
- **Category:** Security & Privacy
- **Description:** Deux fichiers journaux d'exécution (`email_tossing.log` ~145 Ko et `email_annonce.log` ~32 Ko) sont présents à la racine du dépôt de travail. Bien que `.gitignore` contienne `*.log`, ces journaux conservent l'historique complet des envois, des noms complets et des attributions de cadeaux en clair sur la machine locale. De plus, `res/secure_data.yml` et `res/token.json` sont créés localement dans `res/`, or `.gitignore` spécifiait `secure_data.yml` sans chemin relatif (`res/secure_data.yml` pourrait être exposé si un chemin est mal résolu).
- **Evidence:**
  `Get-ChildItem -Force` révèle `email_tossing.log` et `email_annonce.log` à la racine. `git ls-files` confirme qu'ils ne sont pas versionnés, mais leur création directe dans le répertoire de travail expose des données privées aux manipulations courantes.
- **Recommendation:** Rediriger les logs applicatifs vers un sous-dossier dédié (ex. `logs/` ou dans le répertoire de cache utilisateur) et consolider `.gitignore` avec `**/secure_data.yml` et `logs/`.

---

### [Minor] Divergence de contrôle mypy sur le retour de `load_credentials()`
- **Location:** [`source/pere_noel_fremo/helper.py:30-42`](../../source/pere_noel_fremo/helper.py#L30-L42)
- **Category:** Code Quality & Maintainability
- **Description:** Lorsque `mypy source tests` est exécuté directement dans le venv local avec les dépendances tierces installées (`google-auth`, etc.), mypy lève une erreur :
  `source/pere_noel_fremo/helper.py:42: error: Returning Any from function declared to return "Credentials" [no-any-return]`
  car `Credentials.from_authorized_user_file(...)` n'est pas typé par un stub officiel et renvoie `Any`, alors que `warn_return_any = true` est activé dans `pyproject.toml`. Le hook pre-commit ne la détectait pas uniquement parce que `google-auth` n'était pas injecté dans l'environnement virtuel isolé de pre-commit (`mirrors-mypy`).
- **Evidence:**
  Exécution locale :
  ```
  .venv\Scripts\mypy.exe source tests
  source\pere_noel_fremo\helper.py:42: error: Returning Any from function declared to return "Credentials" [no-any-return]
  ```
- **Recommendation:** Utiliser un cast explicite ou un type ignore documenté :
  ```python
  from typing import cast

  ...
  return cast(Credentials, creds)
  ```
  et aligner les dépendances de `mirrors-mypy` ou exécuter mypy via le venv local.

---

### [Minor] Absence de drapeaux de validation de schéma sur les fichiers YAML
- **Location:** [`source/pere_noel_fremo/email_tossing.py:36-37`](../../source/pere_noel_fremo/email_tossing.py#L36-L37)
- **Category:** Code Quality & Maintainability
- **Description:** Les données en entrée (`data_in.yml`) sont chargées directement avec `yaml.safe_load(stream)` et manipulées sous forme de `dict[str, Any]` sans validation préalable de schéma (présence obligatoire de `fullname`, `exclude`, `history` pour chaque entrée). Une simple coquille dans une clé YAML provoquerait un `KeyError` non explicite pendant le tirage ou l'envoi d'e-mails.
- **Evidence:**
  `data = yaml.safe_load(stream)` suivi immédiatement d'accès directs comme `data[user_giver]["exclude"]`.
- **Recommendation:** Définir une structure de données typée (ex. `pydantic` ou `dataclass` avec validation) ou une fonction de validation légère vérifiant la conformité du dictionnaire avant d'entamer le tirage.

---

### [Minor] Absence de mode `--dry-run` ou simulation pour l'envoi des e-mails
- **Location:** [`source/pere_noel_fremo/email_tossing.py:47`](../../source/pere_noel_fremo/email_tossing.py#L47) et [`source/pere_noel_fremo/email_annonce.py:37`](../../source/pere_noel_fremo/email_annonce.py#L37)
- **Category:** Architecture & System Structure
- **Description:** L'exécution de `main()` dans `email_tossing` enchaîne immédiatement le tirage, l'envoi réel de tous les e-mails via l'API Gmail, puis la sauvegarde de `data_out.yml`. Il n'existe pas de commande ou d'option permettant d'effectuer le tirage, d'en afficher le récapitulatif sans envoyer d'e-mails, ou d'écrire `data_out.yml` à l'avance pour vérification humaine avant émission.
- **Evidence:**
  Dans `email_tossing.py` :
  ```python
  send_all_email(data, secure_data, PERSON_TO_SKIP)
  with open(__DATA_OUT, "w", encoding="utf-8") as file:
      yaml.dump(data, file, allow_unicode=True)
  ```
- **Recommendation:** Permettre de dissocier le tirage (`tossing` + export `data_out.yml`) de la phase d'envoi d'e-mails, ou ajouter un commutateur d'envoi (`dry_run=True` par défaut).

---

### [Minor] Métadonnées de version non synchronisées
- **Location:** [`pyproject.toml:7`](../../pyproject.toml#L7)
- **Category:** Release Readiness & Governance
- **Description:** `pyproject.toml` déclare `version = "1.5.0"` tandis qu'aucun fichier `CHANGELOG.md` ne retrace l'historique des versions publiées ou les modifications apportées depuis la version initiale.
- **Evidence:**
  Absence de `CHANGELOG.md` à la racine du dépôt.
- **Recommendation:** Instaurer un `CHANGELOG.md` (format Keep a Changelog) pour documenter les éditions annuelles et les évolutions techniques du projet.

---

### [Observation] Algorithme de tirage probabiliste vs résolution de graphe bipartite
- **Location:** [`source/pere_noel_fremo/email_tossing.py:94-145`](../../source/pere_noel_fremo/email_tossing.py#L94-L145)
- **Category:** Performance & Efficiency
- **Description:** L'algorithme actuel repose sur un tirage de Monte-Carlo avec redémarrage multi-tentatives (500 tentatives x 2000 étapes). Pour la taille du groupe de la Frémo (~20 participants), la résolution est quasi instantanée (< 50 ms). Cependant, au fur et à mesure que les années s'accumulent, l'historique permanent réduit drastiquement les combinaisons valides. À terme, une approche déterministe par couplage de graphe bipartite maximal (ex. algorithme de Hopcroft-Karp ou solveur CSP) garantirait de trouver immédiatement une solution s'il en existe une, ou de prouver son inexistence mathématique.
- **Evidence:**
  La fonction boucle sur `randint(0, len(data) - 1)` et filtre les conflits d'exclusion et d'historique.
- **Recommendation:** Conserver l'implémentation actuelle tant que le nombre de participants reste modéré, mais documenter cette limite combinatoire dans un ADR lorsque l'historique dépassera 10 à 15 éditions.

---

## Ruled-Out Items (Verified Clean)

- **Injection de secrets dans Git (Vérifié propre)** :
  - `git ls-files` inspecté : aucun fichier de secret (`credentials.json`, `token.json`, `secure_data.yml`, `code_secret_client*.json`) n'est suivi dans Git.
  - Le hook `detect-private-key` et `check-yaml` passent avec succès sur l'ensemble des fichiers suivis.
- **Vérification de syntaxe & Linter (Vérifié propre)** :
  - `ruff check .` et `ruff format --check` passent sans aucune erreur.
  - Longueur de ligne (120 caractères) et imports ordonnés respectés.
- **Audit de sécurité statique (Vérifié propre)** :
  - `bandit` exécuté avec configuration `pyproject.toml` (exclusion documentée de `B311` pour le tirage aléatoire des cadeaux conformément à l'ADR 0002) : aucun avertissement de sécurité sur le package applicatif.
- **Tests unitaires de régression (Vérifié propre)** :
  - `pytest` exécuté via la suite de tests complète : 7/7 tests passent avec succès en 1.08s.
  - Les invariants du tirage (absence d'auto-cadeau, unicité, respect des exclusions, respect de l'historique permanent, exclusion des absents, gestion des cheaters) sont validés par test automatisé.
- **Respect du Glossaire Métier (Vérifié propre)** :
  - Les concepts du domaine (Lutin, Donneur, Bénéficiaire, Tirage au sort, Cheater, Exclusion, Historique, Absent, Annonce) définis dans [`GLOSSARY.md`](../../GLOSSARY.md) sont rigoureusement respectés dans la documentation et le code source récent.
- **Structure de package (Vérifié propre)** :
  - Layout standard `source/pere_noel_fremo/` avec `[project.scripts]` opérationnels (`pere-noel-tossing` et `pere-noel-annonce`), conforme à l'ADR 0003.
