# 0014. Campagnes d'Annonce de manche et notifications du Défi du lutin

Date: 2026-10-19

## Statut
Accepté

## Contexte
Avec l'instauration du championnat bi-hebdomadaire du Défi du lutin (ADR-0007), 15 manches de déduction logique se débloquent successivement chaque lundi et vendredi à 17h00 du 12 octobre au 4 décembre 2026.
Jusqu'alors, le module `campagne` et l'architecture du cycle de vie de l'Édition (`edition.py`) ne géraient que deux types de courriels : l'**Annonce** (faisant passer l'Édition de `draft` à `announced`) et la **Révélation** (faisant passer l'Édition de `drawn` à `revealed`).
L'envoi régulier de notifications d'ouverture de manche impose de découpler les campagnes modifiant l'état du cycle de vie des campagnes purement informationnelles et incitatives, tout en automatisant l'injection des métadonnées de manche pour éviter les erreurs manuelles sur les 15 manches.

## Décision

1. **Modèle de domaine et découplage du cycle de vie (`GLOSSARY.md`)** :
   - Formalisation de l'**Annonce de manche** : courriel officiel notifiant les Lutins de l'ouverture bi-hebdomadaire d'une nouvelle Grille logique du Défi du lutin, transmettant les informations de l'épreuve et le Lien magique vers l'Espace Lutin.
   - L'Annonce de manche est sans effet sur l'état du cycle de vie de l'Édition (qui reste inchangé : `announced`, `drawn` ou `revealed`). Seuls les envois nominaux d'Annonce et de Révélation font progresser l'Édition.

2. **Périmètre des destinataires** :
   - Par défaut, l'Annonce de manche est adressée à l'ensemble des Lutins actifs (`active = 1`), à l'exclusion des déclarés `Absents`.
   - Ce ciblage large permet de remobiliser les Lutins n'ayant pas encore confirmé leur présence (rappel de la date limite du 1er novembre) et d'informer tous les participants que les manches passées restent rattrapables librement à tout moment (ADR-0007).

3. **Extraction automatique des métadonnées de grille** :
   - La commande lit la définition statique de la manche dans `res/{year}/grilles/manche_{id}.yml`.
   - Les champs `title`, `estimated_time` et `id` sont extraits automatiquement et injectés dans les gabarits de courriel (`{manche_title}`, `{manche_id}`, `{estimated_time}`).

4. **Gabarit HTML bulletproof et identité visuelle (ADR-0010)** :
   - Création de `DEFAULT_MANCHE_TEMPLATE` dans `source/pere_noel_fremo/gabarits.py` adoptant une identité visuelle distincte en « bleu nuit étoilé » (`#1e3a8a` / `#1e40af` avec CTA `#2563eb` et accents ambrés `#d97706`), se démarquant du rouge de l'Annonce et du vert de la Révélation.
   - Conformité stricte aux standards bulletproof : `bgcolor` et `background-color` de repli sous les dégradés CSS, bouton CTA structuré en table HTML dédiée, et balises `<meta>` dual-scheme pour le mode sombre.
   - Support d'un gabarit personnalisé de surcharge optionnel dans `res/{year}/manche_{id}_email.txt`.

5. **Interface en ligne de commande (CLI)** :
   - Ajout de la sous-commande `pere-noel annonce-manche --manche <ID>` dans `cli.py`.
   - Prise en charge des options standard : `--dry-run`, `--no-email`, `--lutin`, `--override-email`, `--subject`, `--template`.

## Conséquences
- Automatisation et fiabilité de l'animation festive du championnat tout au long des 15 manches.
- Préservation de l'intégrité de la machine à états de l'Édition.
- Rendu d'email impeccable garanti sur tous les clients de messagerie (Outlook, Gmail, Apple Mail).
