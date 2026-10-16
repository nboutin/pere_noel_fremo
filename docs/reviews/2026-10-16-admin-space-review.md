# Project Review: Le Père Noël de la Frémo (Espace Admin)

**Date:** 2026-10-16
**Commit:** 96d0787 (branche `develop`, arbre propre, 5 commits Espace Admin après `d74dd62`)
**Stack Profile:** Python (3.10+, FastAPI + SQLite)
**Reviewer:** AI Pair Programmer
**Périmètre:** Espace Admin (ADR-0013) — [admin.py](../../source/pere_noel_fremo/admin.py), routes `/admin*` de [web.py](../../source/pere_noel_fremo/web.py), [config.py](../../source/pere_noel_fremo/config.py), [espace_admin.html](../../source/pere_noel_fremo/templates/espace_admin.html), [espace_admin_login.html](../../source/pere_noel_fremo/templates/espace_admin_login.html), [docker-compose.yml](../../docker-compose.yml), [test_admin.py](../../tests/test_admin.py), [test_admin_summary.py](../../tests/test_admin_summary.py).

## Executive Summary

L'Espace Admin respecte bien l'Admin aveugle : [admin.py](../../source/pere_noel_fremo/admin.py) ne lit jamais la table `attributions`, et le template n'affiche aucun Bénéficiaire. La couche de données est couverte à 100 % (lignes + branches). Les requêtes SQL sont paramétrées, la comparaison du mot de passe se fait en temps constant, et la garde Funnel renvoie bien un 404 furtif. `ruff`, `mypy` et la suite complète (456 tests, couverture 94,51 %) passent.

La défense en profondeur, elle, ne tient pas en production. **Un Blocker est vérifié par script :** quand aucun `admin_session_secret` n'est configuré, [web.py:152](../../source/pere_noel_fremo/web.py#L152) se rabat sans rien dire sur une constante publique du dépôt. N'importe qui peut alors forger un cookie `admin_session` valide sans connaître le mot de passe. Le `res/secure_data.yml` local ne contient pas cette clé, et `docker-compose.yml` ne définit pas `ADMIN_SESSION_SECRET` : le déploiement tel que décrit est donc exposé. Le dernier commit aggrave le problème. Il publie le port 8000 sur toutes les interfaces, à l'encontre de l'ADR-0009, et désactive `Secure` sur le cookie en HTTP. L'Espace Admin devient joignable en clair depuis tout le réseau local.

**Deux constats Major :** l'anti-brute-force se contourne en changeant l'en-tête `X-Forwarded-For` (vérifié). Le bouton « Copier l'URL » construit le Lien magique à partir de l'hôte de la requête au lieu du `base_url` configuré, si bien qu'un accès LAN copie une URL inutilisable pour un Lutin. Le reste relève de l'hygiène : dictionnaire de résultat chargé d'alias redondants, paramètre `res_dir` inutilisé, réponse 429 en JSON, CHANGELOG `[Unreleased]` vide.

---

## Scorecard

| Dimension | Rating | Findings (B/M/m/O) |
|---|---|---|
| Architecture & System Structure | ⚠️ | 0 B / 0 M / 1 m / 1 O |
| Code Quality & Maintainability | ⚠️ | 0 B / 0 M / 3 m / 0 O |
| Security & Privacy | ❌ | 1 B / 2 M / 1 m / 1 O |
| Performance & Efficiency | ✅ | 0 B / 0 M / 1 m / 0 O |
| Release Readiness & Governance | ⚠️ | 0 B / 1 M / 1 m / 0 O |

---

## Detailed Findings

### [Blocker] Secret de session par défaut public : cookie admin forgeable
- **Location:** [web.py:150-152](../../source/pere_noel_fremo/web.py#L150), [config.py:59-63](../../source/pere_noel_fremo/config.py#L59), [docker-compose.yml:12-14](../../docker-compose.yml#L12)
- **Category:** Security
- **Description:** `session_secret = session_sec or "fremo-default-insecure-admin-secret"`. Sans clé `admin_session_secret` dans `secure_data.yml` ni variable `ADMIN_SESSION_SECRET`, le serveur signe et vérifie les sessions avec une constante publiée dans le dépôt. Le jeton vaut simplement `"<timestamp>.<HMAC-SHA256(secret, timestamp)>"` : n'importe qui peut le calculer. La garde Funnel bloque l'accès depuis Internet, mais tout poste du tailnet ou du LAN (voir le constat suivant) obtient l'Espace Admin, avec les noms, les courriels et tous les Liens magiques (donc l'accès à chaque Espace Lutin et à son Bénéficiaire mystère).
- **Evidence:**
  - `grep -c "^admin_session_secret:" res/secure_data.yml` → `0` (seule la présence de la clé a été vérifiée, aucune valeur n'a été lue).
  - `docker-compose.yml` ne définit que `PYTHONUNBUFFERED` et `FREMO_RES_DIR`.
  - Script de sonde (TestClient, `admin_session_secret=""`, mot de passe réel défini) : `create_session_token("fremo-default-insecure-admin-secret", now)` envoyé comme cookie → `GET /admin` → **200**, page Espace Admin rendue.
  - Aucun test ne couvre ce repli ; tous les tests injectent un secret explicite ([test_admin.py:50](../../tests/test_admin.py#L50)).
- **Recommendation:** Refuser de démarrer, ou désactiver les routes `/admin*` (404), si le secret est absent ou fait moins de 32 octets. Supprimer la constante de repli. Ajouter `admin_session_secret` au `secure_data.yml` de production (par exemple `python -c "import secrets; print(secrets.token_urlsafe(48))"`), documenter la clé dans le readme et ajouter un test de non-régression sur le secret manquant.

### [Major] Port 8000 exposé sur tout le LAN en HTTP clair, contraire à l'ADR-0009 et à l'ADR-0013
- **Location:** [docker-compose.yml:8-9](../../docker-compose.yml#L8), [web.py:641-652](../../source/pere_noel_fremo/web.py#L641), [web.py:699-708](../../source/pere_noel_fremo/web.py#L699)
- **Category:** Security / Release
- **Description:** Le commit `96d0787` passe le port de `127.0.0.1:8000:8000` à `8000:8000` et rend `Secure` conditionnel (`secure=is_https`). L'ADR-0009 §2 impose pourtant la liaison loopback (« empêchant toute exposition directe non filtrée sur le réseau local »), et l'ADR-0013 §4 exige un cookie `Secure`. En accès LAN, le mot de passe administrateur et le cookie de session circulent en clair. Couplé au Blocker, tout appareil du Wi-Fi familial peut ouvrir l'Espace Admin. La garde Funnel ne protège pas ce chemin, puisque ni l'en-tête Funnel ni `:10000` ne sont présents.
- **Evidence:** `git show 96d0787 -- docker-compose.yml` montre le diff `- "127.0.0.1:8000:8000"` / `+ "8000:8000"`. Aucune ADR amendée dans ce commit.
- **Recommendation:** Revenir au loopback et passer par le VPN Tailscale (HTTPS via `tailscale serve` sur un port privé). Si l'accès LAN est voulu, amender l'ADR-0009 et l'ADR-0013 en conséquence et lier le port à l'IP LAN précise plutôt qu'à `0.0.0.0`.

### [Major] Anti-brute-force contournable par `X-Forwarded-For`
- **Location:** [web.py:606-611](../../source/pere_noel_fremo/web.py#L606)
- **Category:** Security
- **Description:** La clé du limiteur est la **première** valeur de `X-Forwarded-For`, un en-tête que le client contrôle entièrement. Un proxy, Tailscale compris, ajoute l'IP réelle en fin de liste et laisse la tête fournie par le client. En changeant cette valeur à chaque requête, on obtient un nombre illimité d'essais. L'exigence ADR-0013 §4 (blocage après 5 échecs) n'est donc pas tenue.
- **Evidence:** Script de sonde : 20 `POST /admin/login` erronés avec `X-Forwarded-For: 10.0.0.{i}` → tous **401**, aucun 429. Sans l'en-tête : `[401, 401, 401, 401, 401, 429]`.
- **Recommendation:** Utiliser `request.client.host`. Si un proxy de confiance est présent, prendre la **dernière** entrée ajoutée par ce proxy (ou passer par `uvicorn --proxy-headers --forwarded-allow-ips=127.0.0.1`). Ajouter en complément un compteur global d'échecs, indépendant de l'IP. Couvrir le cas par un test.

### [Major] « Copier l'URL » construit le Lien magique sur l'hôte de la requête
- **Location:** [web.py:685](../../source/pere_noel_fremo/web.py#L685), [espace_admin.html:469](../../source/pere_noel_fremo/templates/espace_admin.html#L469)
- **Category:** Release (défaut visible)
- **Description:** `base_url = str(request.base_url)`. Ouvert depuis `http://<ip-lan>:8000/admin`, le bouton copie `http://<ip-lan>:8000/lutin/<jeton>`, une URL injoignable pour un Lutin hors du domicile, et en HTTP clair. L'ADR-0009 §6 fixe pourtant le `base_url` canonique dans `secure_data.yml` (`https://homelab.tail7d8b91.ts.net:10000`), et c'est lui que les courriels utilisent. Ce bouton sert justement à « l'assistance directe » (ADR-0013 §3) : l'organisateur risque d'envoyer un lien cassé.
- **Evidence:** Lecture du code. Aucun test ne vérifie l'URL copiée par rapport au `base_url` configuré.
- **Recommendation:** Injecter le `base_url` de configuration (le même que pour les courriels) et ne revenir à `request.base_url` que s'il est absent.

### [Minor] Dictionnaire de résultat chargé d'alias redondants
- **Location:** [admin.py:204-221](../../source/pere_noel_fremo/admin.py#L204), [admin.py:246-257](../../source/pere_noel_fremo/admin.py#L246), [admin.py:275-296](../../source/pere_noel_fremo/admin.py#L275), [admin.py:319-333](../../source/pere_noel_fremo/admin.py#L319)
- **Category:** Quality
- **Description:** Chaque Lutin expose le même jeton sous sept clés (`token`, `token_info`, `tokens`, `token_value`, `magic_link`, `url`, et `value` dans `TokenInfo`). `TokenInfo` est construit deux fois. `DefiInfo` duplique trois paires (`manches_resolues`/`solved_manches_count`, `time_seconds`/`total_time_seconds`, `attempts`/`total_attempts`), et les métriques globales sont répétées entre `summary` et `summary.metrics`. Le template ne lit que `presence`, `defi`, `token_value`, `token_sent` et `token_sent_at` ; le reste n'est utilisé que par les tests ou par personne. Les sous-classes de `dict` qui surchargent `__eq__` pour les comparer à une `str` ([admin.py:17-89](../../source/pere_noel_fremo/admin.py#L17)) relèvent de la même logique de compatibilité tous azimuts.
- **Evidence:** `grep` des clés `lutin.*` dans `espace_admin.html` → 5 clés distinctes. `tokens`, `url`, `presence_statut`, `defi_statut` et `token_info` sont absents du template.
- **Recommendation:** Passer à des `@dataclass(frozen=True)` (`LutinSuivi`, `SyntheseEdition`) avec un seul nom par donnée, et ajuster les tests.

### [Minor] Paramètre `res_dir` inutilisé
- **Location:** [admin.py:95](../../source/pere_noel_fremo/admin.py#L95), [web.py:684](../../source/pere_noel_fremo/web.py#L684)
- **Category:** Architecture
- **Description:** `get_admin_edition_summary(..., res_dir=...)` est documenté mais jamais lu dans le corps de la fonction.
- **Recommendation:** Supprimer le paramètre, ou s'en servir pour lire le `base_url` (voir le Major précédent).

### [Minor] Handler de login synchrone qui relit le corps à la main
- **Location:** [web.py:604-639](../../source/pere_noel_fremo/web.py#L604)
- **Category:** Quality
- **Description:** `def post_admin_login` (synchrone) appelle `anyio.from_thread.run(request.body)`, puis analyse le JSON ou le `urlencoded` à la main dans des `except Exception` trop larges ([web.py:630](../../source/pere_noel_fremo/web.py#L630), [web.py:636](../../source/pere_noel_fremo/web.py#L636)). Ces deux branches ne sont pas couvertes par les tests (lignes 630-631 et 636-637 dans le rapport `--cov`). Le test de longueur dans `verify_session_token` ([web.py:80-81](../../source/pere_noel_fremo/web.py#L80)) est du code mort après `"." not in token` et `split(".", 1)`.
- **Recommendation:** Écrire `async def` avec `await request.form()` (ou `Form(...)` si `python-multipart` est acceptable), attraper `UnicodeDecodeError`/`json.JSONDecodeError`, et supprimer la branche morte.

### [Minor] Réponse 429 en JSON brut sur une page HTML
- **Location:** [web.py:613-617](../../source/pere_noel_fremo/web.py#L613)
- **Category:** Quality
- **Description:** Le formulaire HTML reçoit `{"detail": "Trop de tentatives…"}` au lieu de la page de login avec un message d'erreur.
- **Recommendation:** Rendre `espace_admin_login.html` avec `status_code=429` et un message.

### [Minor] Mémoire du limiteur non bornée
- **Location:** [web.py:100-124](../../source/pere_noel_fremo/web.py#L100)
- **Category:** Performance
- **Description:** `_cleanup` ne purge que l'IP de la requête en cours. Combiné à la rotation de `X-Forwarded-For`, chaque valeur forgée ajoute une entrée qui ne sera jamais purgée.
- **Recommendation:** Purger globalement à chaque appel, ou utiliser une structure bornée. La correction du Major XFF supprime la plus grande partie du risque.

### [Minor] Session non révocable à la déconnexion
- **Location:** [web.py:664-674](../../source/pere_noel_fremo/web.py#L664), [web.py:67-96](../../source/pere_noel_fremo/web.py#L67)
- **Category:** Security
- **Description:** Le jeton est sans état (horodatage + HMAC). `/admin/logout` efface le cookie du navigateur, mais une copie volée reste valide 2 h et se renouvelle indéfiniment par glissement ([web.py:700](../../source/pere_noel_fremo/web.py#L700)). Changer le mot de passe n'invalide pas non plus les sessions, puisque le mot de passe n'entre pas dans le HMAC.
- **Recommendation:** Inclure une empreinte du mot de passe (ou une « génération ») dans le message signé, et fixer une durée de vie absolue (par exemple 12 h) en plus du glissement.

### [Minor] CHANGELOG `[Unreleased]` vide
- **Location:** [CHANGELOG.md:8](../../CHANGELOG.md#L8)
- **Category:** Release
- **Description:** Cinq commits `feat(admin)`/`fix(web)` depuis le tag `2026_2.1.1`, mais aucune entrée sous `[Unreleased]`.
- **Recommendation:** Ajouter une entrée « Added : Espace Admin (ADR-0013) » et une entrée « Changed : port LAN, cookie `Secure` conditionnel ».

### [Observation] Le Lien magique copié donne accès à l'Attribution
- **Location:** [espace_admin.html:468-471](../../source/pere_noel_fremo/templates/espace_admin.html#L468)
- **Category:** Security (Admin aveugle)
- **Description:** L'ADR-0013 accepte ce bouton, qui n'est pas un lien cliquable. Mais coller l'URL dans son propre navigateur affiche l'Espace Lutin et le Bénéficiaire mystère. L'Admin aveugle tient donc à une discipline de l'organisateur, pas à une garantie technique.
- **Recommendation:** Ajouter un avertissement discret (« ne pas ouvrir vous-même »), ou rendre l'URL copiable sans qu'elle soit lisible à l'écran.

### [Observation] Garde Funnel fondée sur des en-têtes
- **Location:** [web.py:57-64](../../source/pere_noel_fremo/web.py#L57)
- **Category:** Architecture
- **Description:** La détection repose sur `Tailscale-Funnel-Request` et sur la sous-chaîne `:10000` dans `Host` ou `X-Forwarded-Host`. C'est correct tant que Tailscale positionne ces en-têtes et que l'application n'est joignable que par `tailscale serve/funnel`. Le passage en `0.0.0.0:8000` sort de cette hypothèse.
- **Recommendation:** ⏸️ Not verified — requires physical runtime/device : sur le homelab, faire `curl -I https://homelab.tail7d8b91.ts.net:10000/admin` depuis un réseau hors tailnet (4G) → 404 attendu ; depuis le tailnet → 303 vers `/admin/login`.

---

## Ruled-Out Items (Verified Clean)

- **Admin aveugle (données) :** `grep attributions admin.py` ne trouve que des docstrings (l. 5, 100), aucune requête. Aucune occurrence de `beneficiaire` dans [espace_admin.html](../../source/pere_noel_fremo/templates/espace_admin.html). Les requêtes de [admin.py:113-155](../../source/pere_noel_fremo/admin.py#L113) portent sur `editions`, `lutins`, `presences`, `tokens` et `scores_defi` uniquement.
- **Injection SQL :** les six requêtes de `get_admin_edition_summary` sont paramétrées (`?`).
- **Gestion des connexions :** `with connection(db_path)` ([database.py:119-128](../../source/pere_noel_fremo/database.py#L119)) ferme la connexion qu'il a ouverte.
- **Comparaison du mot de passe :** `hmac.compare_digest` sur des octets ([web.py:639](../../source/pere_noel_fremo/web.py#L639)). Un mot de passe absent refuse tout (`bool(admin_pwd and …)`).
- **Signature de session :** HMAC-SHA256 avec `compare_digest`, rejet des horodatages futurs (+300 s) et expirés ([web.py:76-96](../../source/pere_noel_fremo/web.py#L76)).
- **Cookie :** `HttpOnly` et `SameSite=Strict` sur login, renouvellement et logout. `Secure` est conditionnel (voir le Major sur le port).
- **CSRF :** l'espace est en lecture seule (aucune route d'écriture hors login/logout), et le cookie est `SameSite=Strict`.
- **Garde Funnel (chemin) :** `path.lower()` couvre `/admin` et le préfixe `/admin/`. Starlette décode `scope["path"]` avant le middleware et le routage, si bien que l'encodage `%61dmin` ne contourne rien.
- **Discrétion :** `grep -rl "/admin" templates/` → seulement `espace_admin.html` et `espace_admin_login.html`. Aucun lien depuis `/scores` ou `/lutin/{token}`.
- **XSS du template :** autoescape Jinja2 actif (`Jinja2Templates`, `.html`). Nom, courriel et dates passent par `{{ }}`. Le jeton injecté dans `onclick` est généré par le serveur.
- **Vérifications outillées :** `uv run pytest -q` → 456 passed, 2 skipped, couverture 94,51 % (seuil 92 %). Sous-ensemble admin et config : 47 passed. `admin.py` et `config.py` à 100 % ; `web.py` à 60 %, mais les lignes admin non couvertes se limitent à 81, 118 et 628-639. `uv run ruff check source tests` → All checks passed. `uv run mypy source` → no issues in 19 files.
- **Glossaire :** le terme canonique « Espace Admin » est employé partout. Aucune variante proscrite (`dashboard`, `backoffice`, `panneau de contrôle`, `console`) dans `source/`.
