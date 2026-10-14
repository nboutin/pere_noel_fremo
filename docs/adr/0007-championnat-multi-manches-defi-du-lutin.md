# ADR 0007 : Championnat bi-hebdomadaire du Défi du lutin et protection anti-triche IA

## Contexte
Le Défi du lutin vise à créer une émulation festive continue et à déterminer l'ordre d'ouverture des cadeaux lors du réveillon (fixé au **dimanche 5 décembre 2027** entre amis).
La version initiale à manche unique ne permettait ni bataille de classement ni rejouabilité. De plus, l'avènement des modèles d'IA générative (LLM / OCR multimodaux) capables de résoudre un logigramme textuel ou une capture d'écran en quelques secondes impose une protection robuste pour préserver l'équité du chronomètre.

## Décisions

1. **Format Championnat bi-hebdomadaire à points (Grand Prix)** :
   - Le Défi du lutin est découpé en **Manches** bi-hebdomadaires (déblocage chaque **lundi à 19h00** et chaque **vendredi à 19h00**).
   - Coup d'envoi le **vendredi 16 octobre 2027 à 19h00**, menant au réveillon du **dimanche 5 décembre 2027** (soit 15 manches au total).
   - Chaque Manche propose une **Grille logique** distincte.
   - Sur chaque manche, un Lutin ne dispose que d'**un seul essai officiel** (chronométré au dixième de seconde).
   - Chaque manche attribue des points selon le rang de vitesse parmi les Lutins ayant résolu la grille :
     * 1er : 10 pts, 2e : 8 pts, 3e : 6 pts, 4e : 5 pts, 5e : 4 pts, 6e : 3 pts, 7e : 2 pts, 8e et suivants : 1 pt (prime de complétion).
   - Les points de chaque manche sont recalculés dynamiquement en direct à chaque nouveau score enregistré.
   - Le **Tableau des scores** général classe les Lutins par **points cumulés décroissants**, avec départage en premier lieu par le nombre de manches résolues avec succès, puis par temps total cumulé croissant sur les manches réussies.
   - **Neutralisation de la force brute et limitation des soumissions** :
     * Chaque Lutin dispose d'un plafond strict de **3 soumissions de validation** (`MAX_ESSAIS_PAR_MANCHE = 3`) par manche.
     * Chaque soumission erronée précédant la réussite applique une pénalité forfaitaire de **15 secondes** (`PENALITE_ESSAI_FAUX_SECONDES = 15`) ajoutée au temps officiel chronométré.
     * En cas d'échec à la 3e soumission, la manche est automatiquement scellée comme abandonnée (`completed_at = now`, `solved = 0`, `time_seconds = NULL`). Le Lutin reçoit **1 point de participation** pour avoir combattu jusqu'au bout.
     * Un abandon volontaire en cours d'épreuve sans avoir consommé ses 3 soumissions n'octroie aucun point (0 pt).
     * Seules les soumissions complètes mais logiquement erronées consomment un essai ; les requêtes incomplètes ou malformées sont rejetées sans pénalité ni décompte.

2. **Déverrouillage progressif et rattrapage libre** :
   - Chaque manche possède une date d'ouverture (`unlock_at`).
   - Un Lutin peut rattraper à tout moment les manches passées déjà déverrouillées jusqu'au réveillon du 5 décembre 2027.
   - Aucune manche passée n'est pénalisée ni fermée prématurément.

3. **Protection multicouche anti-capture et anti-triche IA (Défense en profondeur)** :
   Pour neutraliser la transmission immédiate de l'énigme à une IA (ChatGPT, Claude, etc.) pendant le chronomètre :
   - **Couche A : Rendu visuel Canvas avec filigrane bruité** : Les indices ne sont pas injectés en texte DOM copiable mais dessinés dynamiquement sur un composant HTML5 Canvas avec un motif de flocons de neige semi-transparents qui perturbe l'OCR automatique sans gêner la lisibilité humaine.
   - **Couche B : Fragmentation interactive des indices (onglets / un par un)** : Les indices sont masqués par défaut et ne peuvent être consultés qu'un par un au clic sur des onglets/cartes dédiés. Il est impossible de faire une capture d'écran unique de l'ensemble de l'énigme sans manipulations répétées très coûteuses en temps.
   - **Couche C : Protections navigateur contre la copie** : Désactivation du menu contextuel (clic droit), `user-select: none`, et masquage d'urgence de la zone de jeu en cas de perte de focus (`window.onblur` / bascule d'onglet).
   - **Friction incompressible du prompt IA** : Le temps humain nécessaire pour capturer plusieurs fragments, basculer d'application, uploader, attendre la génération et recopier les résultats excède le temps de résolution directe de tête par un joueur concentré (30 à 50s).

4. **Organisation modulaire des grilles statiques** :
   - Chaque manche est stockée dans un fichier YAML dédié : `res/{YEAR}/grilles/manche_{ID}.yml`.
   - Chaque fichier spécifie : `id`, `title`, `unlock_at`, `estimated_time`, `categories`, `indices`, `solution`.

5. **Modélisation en base de données** :
   - La table des scores enregistre la granularité par manche :
     `scores_defi (lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at)` avec clé primaire `(lutin_id, year, manche_id)`.

6. **Expérience joueur & Bataille de classement** :
   - Sur l'Espace Lutin, l'affichage montre l'état de chaque manche (Verrouillée 🔒, Disponible 🚀, Résolue ✅), les points gagnés, le classement général et le podium avec les écarts de points.

## Conséquences
- Émulation collective bi-hebdomadaire forte du 16 octobre au 5 décembre 2027.
- Équité préservée face aux outils d'IA et au partage de copies d'écran.
- Rattrapage flexible et sans stress pour les participants.
