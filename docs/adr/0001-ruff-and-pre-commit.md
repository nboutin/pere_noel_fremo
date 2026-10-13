# Migration vers Ruff et adoption de pre-commit

## Contexte
Le projet utilisait historiquement flake8 (`.flake8`) et pylint (`.pylintrc`) sans hook de vérification automatisé avant commit. Les contrôles de propreté (yaml, whitespace, secrets) reposaient sur des vérifications manuelles.

## Décision
1. Adopter le framework `pre-commit` avec les hooks standard (nettoyage d'espaces, conformité YAML, détection de clés privées).
2. Remplacer flake8 et pylint par **Ruff** (linter et formatter) configuré dans `pyproject.toml` avec une longueur de ligne de 120 caractères.
3. Intégrer `ruff check --fix` et `ruff format` dans le cycle pre-commit.
4. Supprimer les fichiers obsolètes `.flake8` et `.pylintrc`.
