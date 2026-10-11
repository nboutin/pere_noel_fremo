# Renforcement de la chaîne de qualité et sécurité Python

## Contexte
Après la mise en place initiale de `pre-commit` et `Ruff`, nous souhaitons durcir les contrôles de qualité, de sécurité et d'hygiène de code sur les scripts Python du projet.

## Décision
1. **Typage statique (Mypy)** : Intégrer `mypy` via le hook `mirrors-mypy` et annoter le code Python du dépôt.
2. **Audit de sécurité (Bandit)** : Intégrer `bandit` via `PyCQA/bandit` pour analyser statiquement les vulnérabilités courantes (avec exclusion du contrôle pseudo-aléatoire `B311` pour l'algorithme de tirage au sort des cadeaux).
3. **Hygiène syntaxique Python** : Activer les hooks officiels `check-ast`, `debug-statements`, `check-docstring-first` et `check-builtin-literals`.
4. **Extension des règles Ruff** : Étendre les règles de linting dans `pyproject.toml` avec `B` (Bugbear), `UP` (Pyupgrade), `SIM` (Simplify) et `PIE` (Flake8-pie).
