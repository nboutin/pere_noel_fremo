# 0010. Date du Repas de Noël dans l'Espace Lutin et métadonnées d'édition

Date: 2026-10-14

## Statut
Accepté

## Contexte
Historiquement, la date limite de confirmation de présence et la date de la remise des cadeaux étaient mentionnées uniquement dans les courriels statiques d'annonce. Dans l'Espace Lutin interactif, la section de « Confirmation de présence » demandait génériquement *« Participeras-tu à l'échange de cadeaux cette année ? »*, sans préciser la date du rassemblement. Les Lutins devaient donc se référer à leur boîte mail pour connaître le jour du rassemblement.

De plus, le modèle de domaine nécessitait une clarification lexicale : le rassemblement annuel était nommé diversement (« fête », « repas de Noël », « événement »), sans terme canonique unifié dans `GLOSSARY.md`.

## Décision

1. **Terminologie de domaine (`GLOSSARY.md`)** :
   - Formalisation du terme canonique **Repas de Noël** : rassemblement rituel annuel réunissant les Lutins pour célébrer le Père Noël secret, au cours duquel le vainqueur du Défi du lutin ouvre son cadeau en premier avant la distribution générale des cadeaux.
   - Exclusion formelle des variantes : *Fête*, *Fête de Noël*, *Événement*, *Soirée*, *Party*, *Banquet*.

2. **Source de vérité déclarative YAML** :
   - Stockage de la date dans le fichier d'entrée déclaratif `res/{year}/data_in.yml` sous une clé réservée racine `_edition` :
     ```yaml
     _edition:
       date_repas: "2026-12-05"
     ```
   - La clé `_edition` est isolée et ignorée par l'énumération des Lutins, des exclusions et de l'historique lors de l'importation.

3. **Persistance SQLite (`res/fremo.db`)** :
   - Ajout d'une colonne optionnelle `date_repas TEXT` dans la table `editions`.
   - Migration automatique et idempotente dans `init_db()` via `PRAGMA table_info(editions)`.
   - Synchronisation automatique lors de `import_yaml_data()`.

4. **Formatage dynamique et zéro dépendance (`helper.py`)** :
   - Stockage au format ISO `YYYY-MM-DD` (sans heure).
   - Formatage en français standard (*« samedi 5 décembre 2026 »*) sans dépendance externe tierce.
   - Calcul dynamique du compte à rebours : `(J-xx)` avant l'échéance, `Aujourd'hui ! 🎅` le jour J, et `(Passé)` ultérieurement.

5. **Double affichage dans l'Espace Lutin (`espace_lutin.html`)** :
   - **En-tête principal** : badge dédié à côté du millésime (`📅 Repas de Noël : samedi 5 décembre 2026 (J-52)`).
   - **Carte Confirmation de présence** : conservation de la question d'origine enrichie du rappel précis de la date (`📅 Date du Repas de Noël : samedi 5 décembre 2026 (J-52)`).

## Conséquences
- Les Lutins disposent en permanence de la date du Repas de Noël et du décompte des jours directement sur leur Espace Lutin.
- Le cycle de vie des éditions intègre une date de rassemblement versionnée et persistée sans rupture de compatibilité.
- Rétrocompatibilité totale pour les éditions historiques antérieures où `date_repas` est `NULL` (masquage gracieux des badges).
