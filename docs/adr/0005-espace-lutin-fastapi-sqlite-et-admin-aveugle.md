# Espace Lutin, persistance SQLite et mode Admin aveugle

## Contexte
Historiquement, le Père Noël de la Frémo s'appuyait sur des scripts CLI uniques (`email_annonce.py`, `email_tossing.py`), des fichiers YAML statiques dans `res/{YEAR}/`, et un fichier texte manuel `presence.md`. Les résultats du tirage au sort étaient affichés en clair dans les journaux d'exécution et les fichiers de sortie, ce qui gâchait systématiquement la surprise pour l'organisateur (qui ne pouvait pas ignorer son propre Donneur). De plus, l'expérience des Lutins se limitait à un simple email brut contenant le prénom de leur Bénéficiaire.

Pour enrichir l'expérience rituelle (cartes à gratter, énigmes de la luge) et automatiser la collecte des présences sans manipulation manuelle, une interface interactive personnalisée est requise.

## Décision
1. **Espace Lutin Web (FastAPI)** : Mettre en place un service web Python léger (FastAPI) déployable sur infrastructure personnelle (Homelab / Docker), servant une page dédiée par Lutin.
2. **Liens magiques opaques** : L'authentification repose sur des jetons aléatoires cryptographiques opaques générés via `secrets.token_urlsafe(16)` envoyés par email, dispensant les Lutins de tout compte ou mot de passe.
3. **Persistance SQLite (`res/fremo.db`)** : Remplacer la manipulation manuelle des fichiers intermédiaires par une base SQLite locale pour gérer l'état de l'édition courante (Lutins, tokens de session, confirmations de présence, scores du Défi de la luge et attributions), avec pont d'import/export YAML pour préserver l'historique pérenne.
4. **Mode Admin aveugle et audit par agent** :
   - Le tirage reste déclenché par une commande CLI explicite.
   - La sortie console et les logs publics masquent l'identité du Donneur de l'organisateur ainsi que les attributions complètes (`*** SECRET ***`).
   - La persistance en base et les journaux détaillés restent auditables et exploitables par l'agent Antigravity pour assister l'organisateur en cas d'incident sans briser son anonymat de joueur.
5. **Cycle de vie en deux phases** :
   - *Phase 1 (Annonce)* : Email avec Lien magique permettant à chaque Lutin de valider ou décliner sa présence.
   - *Phase 2 (Tirage et Défi)* : Déclenchement du tirage parmi les Lutins confirmés, email invitant à se reconnecter à l'Espace Lutin pour résoudre le Défi de logique/énigme et gratter sa carte de Bénéficiaire.
