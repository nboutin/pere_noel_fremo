# Restructuration en layout de package source

## Contexte
Les scripts Python résidaient directement à la racine du dépôt sans organisation en package distributable, et référençaient les chemins de ressources via des chemins relatifs au répertoire de travail courant d'exécution.

## Décision
1. Déplacer le code applicatif sous le dossier `source/pere_noel_fremo/` avec un package standard (`__init__.py`).
2. Conserver le dossier `poc/` à la racine pour les scripts expérimentaux.
3. Résoudre les chemins de ressources de manière absolue par rapport à la racine du projet (`Path(__file__).resolve().parent.parent.parent / "res"`).
4. Déclarer les scripts CLI `pere-noel-tossing` et `pere-noel-annonce` dans `pyproject.toml` (`[project.scripts]`) et installer le package en mode éditable (`pip install -e .`).
