# Architecture du Défi de la luge, Carte à gratter et Tableau des scores

## Contexte
Le Père Noël de la Frémo intègre deux rituels distincts au sein de l'Espace Lutin :
1. **La révélation du Bénéficiaire** : rituel intime où le Donneur découvre à qui il offre un cadeau une fois le tirage au sort scellé.
2. **Le Défi de la luge** : compétition ludique collective sous forme de Grille logique chronométrée permettant d'établir un classement public (Tableau des scores) sous des Pseudos de lugeur anonymes, afin de déterminer quel Lutin ouvrira son cadeau en premier le soir du réveillon.

Initialement, le ticket 13 suggérait que la résolution de la grille conditionnait l'accès au Bénéficiaire. La clarification de domaine a établi que ces deux flux sont totalement découplés.

## Décisions

1. **Découplage complet entre Défi de la luge et Carte à gratter** :
   - La **Carte à gratter** est accessible dès que le tirage au sort de l'édition est effectué (`editions.status IN ('drawn', 'revealed')`). Elle révèle le Bénéficiaire directement via un composant HTML5 Canvas grattable, avec persistance locale / serveur pour ne pas forcer à re-gratter lors des visites ultérieures.
   - Le **Défi de la luge** est indépendant du tirage au sort : il est accessible dès que le Lutin a validé sa **Confirmation de présence** (« Je participe »).

2. **Grille logique festive et équité** :
   - La Grille logique est commune à l'ensemble des Lutins pour une édition donnée, assurant une stricte équité de chronométrage.
   - Elle est configurée dans `res/{YEAR}/defi_grille.yml` (ou un gabarit par défaut) comprenant les catégories, éléments et indices croisés.
   - L'interface interactive permet de cocher/barrer cases et indices sans blocage immédiat ni pénalité arbitraire ; la soumission vérifie la complétude et l'exactitude de la solution côté serveur.

3. **Tentative unique et chronométrage inviolable** :
   - Le chronométrage est validé côté serveur : la colonne `started_at TIMESTAMP` dans `scores_defi` consigne l'heure de début lors de l'appel `POST /api/lutin/{token}/defi/start`.
   - Le temps final `time_seconds` est calculé côté serveur lors de la validation `POST /api/lutin/{token}/defi/solve`.
   - Un seul essai officiel est consigné dans `scores_defi`. Une fois résolue, la grille reste consultable mais le temps n'est plus modifiable.

4. **Pseudos de lugeur stables et anonymes** :
   - Chaque Lutin se voit attribuer un Pseudo de lugeur festif généré de manière pseudo-aléatoire mais déterministe (hachage stable de `lutin_id` et `year` avec sel cryptographique piochant dans une liste d'adjectifs et noms d'animaux/créatures d'hiver).
   - Le pseudo est persisté dans `scores_defi` dès l'attribution.

5. **Tableau des scores permanent et public** :
   - Accessible en permanence sur chaque Espace Lutin (avec mise en valeur du pseudo et du rang personnel).
   - Également exposé sur une route publique (`/scores` ou `/scores/{year}`) sans nécessiter de Lien magique pour affichage collectif lors de la fête.

6. **Expérience de la Carte à gratter** :
   - Le composant tactile/souris Canvas dissimule le nom du Bénéficiaire.
   - L'état « déjà gratté » est mémorisé côté client en `localStorage` pour ne pas réimposer le grattage lors des visites ultérieures, tout en conservant une option pour revoir l'animation à volonté.

## Conséquences
- Expérience utilisateur fluide et engageante : un Lutin n'est pas bloqué pour préparer son cadeau s'il tarde à faire le jeu.
- Le suspense sur l'identité du vainqueur de la luge est préservé jusqu'à la fête de Noël grâce aux Pseudos de lugeur.
- Répétabilité annuelle simple grâce à la configuration YAML de la Grille logique.
