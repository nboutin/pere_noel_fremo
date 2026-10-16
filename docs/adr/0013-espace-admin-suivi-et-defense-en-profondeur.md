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
   - **Isolation réseau (Rejet Tailscale Funnel)** : le middleware ou la garde de route inspecte les en-têtes HTTP de la requête (`Tailscale-Funnel-Request: ?1`, en-tête `Host` / `X-Forwarded-Host` ciblant le port public 10000). Toute requête vers `/admin` ou `/admin/*` provenant du Funnel public est rejetée avec un code **HTTP 404 (Not Found)** furtif. L'Espace Admin est ainsi rendu totalement inexistant pour le trafic Internet public et réservé aux connexions via le VPN privé Tailscale ou le réseau local.
   - **Authentification par mot de passe fort** : formulaire d'authentification sur `/admin/login`. Le mot de passe d'administration est défini dans `res/secure_data.yml` sous la clé `admin_password` et peut être surchargé par la variable d'environnement `ADMIN_PASSWORD`.
   - **Limitation de débit (Anti-brute force)** : blocage temporaire ou temporisation des requêtes après 5 tentatives infructueuses consécutives.
   - **Session chiffrée / signée** : émission d'un cookie de session sécurisé (`HttpOnly`, `SameSite=Strict`, `Secure`), d'une durée de validité de 2 heures d'inactivité, avec bouton de déconnexion explicite (`/admin/logout`).
   - **Discrétion absolue** : aucun lien ou référence vers `/admin` n'apparaît sur les pages publiques (`/scores` ou `/lutin/{token}`).

## Conséquences
- L'organisateur dispose d'une interface claire et centralisée pour suivre l'édition en cours depuis ses appareils connectés au VPN Tailscale.
- Le secret des cadeaux est préservé à 100 % pour l'organisateur grâce au respect rigoureux de l'Admin aveugle.
- La surface d'attaque publique via Tailscale Funnel reste nulle (réponse 404 furtive sur les flux Funnel).
