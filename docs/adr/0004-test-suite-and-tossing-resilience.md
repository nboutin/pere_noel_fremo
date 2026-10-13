# Harnais de tests de non-régression et résilience du tirage au sort

## Contexte
Le projet ne comportait aucun test automatisé de non-régression. L'algorithme de tirage au sort `tossing()` reposait sur une boucle gloutonne sans retour en arrière : lors d'impasses partielles dues aux exclusions ou à l'historique, il bouclait inutilement jusqu'à 100 000 itérations sans réinitialiser la tentative en cours. De plus, `__CHEATERS` était codé en dur au niveau du module sans possibilité d'injection lors des tests.

## Décision
1. **Framework de test** : Adopter `pytest` et structurer les tests dans un dossier racine `tests/`.
2. **Paramétrage des cheaters** : Rendre la liste des cheaters injectable dans `tossing(data, to_skip=..., cheaters=...)` avec fallback par défaut sur `__CHEATERS`.
3. **Résilience de l'algorithme** : Découper `tossing()` en tentatives distinctes (`MAX_ATTEMPTS`) avec détection d'impasse locale (`MAX_STEPS_PER_ATTEMPT`) pour réinitialiser et retenter instantanément un tirage complet en cas de blocage.
4. **Couverture des tests** :
   - Invariants du tirage au sort : bijections strictes, absence d'auto-cadeau, respect des exclusions, respect de l'historique permanent, exclusion des absents, respect des paires imposées de cheaters, et échec propre si aucune solution n'existe.
   - Génération de messages : structure multipart MIME, intégration d'images et mocks d'envoi Gmail.
5. **Intégration continue locale** : Exécuter `pytest` dans les hooks `pre-commit` avant chaque commit.
