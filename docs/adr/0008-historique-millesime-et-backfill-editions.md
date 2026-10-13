# 0008. Historique millésimé, backfill des attributions et synchronisation des éditions

Date: 2026-10-13

## Statut
Accepté

## Contexte
Lors de l'initialisation de la base SQLite `res/fremo.db` via `import_yaml_data`, les attributions issues de l'array `history` de `res/2025/data_in.yml` ont été insérées avec `year = NULL`. De plus :
1. Le tirage de l'édition 2025 (présent dans `res/2025/data_out.yml`) n'a pas été inséré en base lors de l'import initial.
2. Un tirage prématuré pour l'édition 2026 a été exécuté en base alors que les Lutins n'avaient pas encore tous validé leur participation, et sans avoir connaissance du tirage 2025, entraînant deux collisions interdites (`schouteau -> fxduret` et `mberthet -> ccarre`).
3. L'array `history` des Lutins est de longueur variable (de 1 pour un Lutin récent à 10 pour un Lutin fondateur) : un simple calcul linéaire d'années à partir des index corromprait la chronologie réelle.

## Décision
1. **Rattachement millésimé exact** :
   Reconstituer l'historique exact (2014 à 2025) en croisant les instantanés YAML d'archives (`res/__bk/data_2018.yml`, `data_2019.yml`, `data_export_2021.yml`, `2022/data_out_2022.yml`, `2023/2023_data_out.yml`, `2024/data_out.yml`, `2025/data_out.yml`). Chaque attribution de chaque Donneur se voit assigner son millésime réel exact (`year`).

2. **Synchronisation de la table `editions`** :
   Pour satisfaire l'intégrité référentielle (`attributions.year REFERENCES editions(year)`), insérer chaque millésime historique (2014 à 2025) dans la table `editions` avec le statut `'drawn'`.

3. **Intégration du tirage 2025** :
   Insérer les 25 attributions de l'édition 2025 avec `year = 2025` et leur `order_index` adéquat.

4. **Annulation du tirage 2026 prématuré** :
   Purger les 26 attributions enregistrées pour l'édition 2026 et basculer le statut de l'édition 2026 de `'drawn'` à `'announced'`, afin de permettre aux Lutins de continuer à confirmer leur présence. Le tirage 2026 sera effectué lorsque toutes les présences seront confirmées.

5. **Fonction idempotente dans `database.py`** :
   Centraliser la logique de reconstitution et de mise à niveau dans `backfill_historical_attributions(db_path, res_dir)`.

## Conséquences
- Zéro valeur `NULL` dans la colonne `year` de la table `attributions`.
- Respect strict de l'invariant d'unicité historique pour tous les tirages futurs.
- Intégrité référentielle garantie sur la clé étrangère `editions(year)`.
- Réouverture du formulaire de confirmation de présence pour l'édition 2026.
