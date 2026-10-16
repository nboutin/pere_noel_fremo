# 0013. Espace Admin de suivi des Lutins et défense en profondeur

Date: 2026-10-16

## Statut
Accepté

## Contexte
Avec l'automatisation de l'Espace Lutin, de la confirmation de présence en ligne et du championnat multi-manches du Défi du lutin, l'organisateur a besoin de suivre l'avancement de chaque Édition : identifier qui a confirmé sa présence, qui est absent, qui n'a pas encore répondu, quels Liens magiques ont été distribués, et quelle est la progression des Lutins sur les grilles logiques.

Jusqu'alors, ce suivi nécessitait des requêtes manuelles dans SQLite ou des commandes d'audit CLI. Cette méthode est peu ergonomique depuis un smartphone et présente un risque majeur : celui d'afficher par inadvertance les tables d'attributions et de gâcher la surprise de l'organisateur, violant ainsi le principe fondamental d'**Admin aveugle** (ADR-0005).

Par ailleurs, l'application FastAPI est exposée publiquement sur Internet sans authentification préalable pour les Lutins via Tailscale Funnel sur le port 10000 (ADR-0009). Déployer une interface d'administration sur ce même serveur exige une sécurité sans faille afin d'interdire tout accès public non autorisé et de protéger les données personnelles des membres.

## Décision

1. **Terminologie de domaine (`GLOSSARY.md`)** :
   - Formalisation du terme canonique **Espace Admin** : page web confidentielle réservée à l'organisateur pour suivre l'état d'avancement de l'édition (statut de présence des Lutins, Absents, envois des Liens magiques et progression au Défi du lutin), tout en respectant strictement l'Admin aveugle en masquant toute Attribution.
   - Exclusion formelle des variantes : *Dashboard admin*, *Panneau de contrôle*, *Console*, *Backoffice*, *Interface de gestion*.

2. **Périmètre en consultation seule et préservation de l'Admin aveugle** :
   - L'Espace Admin est strictement limité à la **consultation** (lecture seule) afin d'éviter tout effet de bord accidentel depuis le web. Les opérations d'écriture structurelles (tirage, campagnes d'envoi d'emails) demeurent l'apanage exclusif des commandes CLI auditées.
   - **Garantie absolue d'Admin aveugle** : le contrôleur et les requêtes de l'Espace Admin ignorent délibérément la table `attributions`. Aucune donnée relative aux couples Donneur-Bénéficiaire n'est chargée en mémoire ni rendue dans le template Jinja2.

3. **Indicateurs opérationnels et synthèse** :
   - **Bandeau de synthèse** en tête de page : cartes récapitulatives affichant le nombre total de Lutins inscrits, le nombre de Confirmés (présents), le nombre d'Absents, le nombre en attente de réponse, le nombre de Liens magiques envoyés, et le taux de résolution du Défi du lutin.
   - **Tableau détaillé filtrable** : liste exhaustive des Lutins avec statut d'activation (`is_active`), statut de présence (*Confirmé*, *Absent*, *En attente*), statut d'envoi du Lien magique (avec date et bouton de copie de l'URL pour assistance directe), et statut sur le Défi du lutin (*Non commencé*, *En cours*, *Résolu*, *Abandonné*).
   - **Sélecteur multi-éditions** : consultation rétroactive de l'historique des éditions précédentes via un sélecteur d'année.

4. **Défense en profondeur et sécurité d'accès** :
   - **Isolation réseau (Rejet Tailscale Funnel)** : le middleware ou la garde de route inspecte les en-têtes HTTP de la requête (`Tailscale-Funnel-Request: ?1`, en-tête `Host` / `X-Forwarded-Host` ciblant le port public 10000). Toute requête vers `/admin` ou `/admin/*` provenant du Funnel public est rejetée avec un code **HTTP 404 (Not Found)** furtif. L'Espace Admin est ainsi rendu totalement inexistant pour le trafic Internet public et réservé aux connexions via le VPN privé Tailscale ou le réseau local. *Amendé le 16 octobre 2026 : l'isolation ne repose plus sur l'inspection d'en-têtes. Les ports Funnel et `serve` pointaient vers le même backend, que seuls des en-têtes (dont `Host`, contrôlé par le client) permettaient de distinguer. L'Espace Admin est désormais une application distincte (`create_admin_app`, commande `pere-noel serve-admin`), exécutée dans un second service compose (`pere_noel_fremo_admin`) qui écoute sur `127.0.0.1:8001` et n'est joignable que via `tailscale serve` sur le port 8444 (ADR-0009). L'application publique ne déclare plus aucune route `/admin*` : celles-ci y répondent comme n'importe quelle URL inconnue. Un garde-fou subsiste sur l'application d'administration : 404 si l'en-tête `Tailscale-Funnel-Request: ?1` est présent, au cas où un port Funnel serait pointé par erreur vers `:8001`. Le test sur `:10000` est supprimé et le réseau local n'est plus un canal d'accès. Comme le service peut être arrêté depuis Dockge entre deux Éditions, « Espace Admin désactivé » se résume à un service arrêté.*
   - **Authentification par mot de passe fort** : formulaire d'authentification sur `/admin/login`. Le mot de passe d'administration est défini dans `res/secure_data.yml` sous la clé `admin_password` et peut être surchargé par la variable d'environnement `ADMIN_PASSWORD`.
   - **Limitation de débit (Anti-brute force)** : blocage temporaire ou temporisation des requêtes après 5 tentatives infructueuses consécutives. *Amendé le 16 octobre 2026 : derrière `tailscale serve`, la liaison loopback et le NAT Docker, l'application voit tous les clients sous l'adresse de la passerelle Docker. Le limiteur est donc global en pratique, ce qui est accepté puisque le tailnet ne contient que les appareils de l'organisateur. Les en-têtes `X-Forwarded-For` et `Tailscale-User-Login` ne sont pas utilisés pour identifier le client.*
   - **Session chiffrée / signée** : émission d'un cookie de session sécurisé (`HttpOnly`, `SameSite=Strict`, `Secure`), d'une durée de validité de 2 heures d'inactivité, avec bouton de déconnexion explicite (`/admin/logout`). *Amendé le 16 octobre 2026 : `Secure` est inconditionnel, sans déduction depuis le schéma ou `X-Forwarded-Proto`. Tout accès distant passe par HTTPS via `tailscale serve`, et les navigateurs considèrent `http://localhost` comme un contexte sécurisé pour le développement local.* *Amendé le 16 octobre 2026 : la session a aussi une durée de vie absolue de 12 heures depuis la connexion, quelle que soit l'activité, et la signature du cookie lie une empreinte SHA-256 de `admin_password` : changer ce mot de passe révoque toutes les sessions en cours.*
   - **Discrétion absolue** : aucun lien ou référence vers `/admin` n'apparaît sur les pages publiques (`/scores` ou `/lutin/{token}`).

## Conséquences
- L'organisateur dispose d'une interface claire et centralisée pour suivre l'édition en cours depuis ses appareils connectés au VPN Tailscale.
- Le secret des cadeaux est préservé à 100 % pour l'organisateur grâce au respect rigoureux de l'Admin aveugle.
- La surface d'attaque publique via Tailscale Funnel reste nulle (réponse 404 furtive sur les flux Funnel). *Amendé le 16 octobre 2026 : cette nullité est désormais structurelle, puisque le processus ciblé par Funnel ne contient pas le code de l'Espace Admin. En contrepartie, le déploiement comprend un second service compose et un second port `tailscale serve` à configurer sur le Homelab.*
