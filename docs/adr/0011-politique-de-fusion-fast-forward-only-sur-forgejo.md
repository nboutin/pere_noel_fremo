# Politique de fusion Fast-Forward Only sur Forgejo et hygiène des branches

## Contexte
Le cycle d'intégration continue et de revue de code du projet Père Noël de la Frémo s'appuie sur l'instance Forgejo du homelab (`nbt1/pere_noel_fremo`).
Par défaut, le dépôt autorisait l'ensemble des modes de résolution de pull requests (`merge_commits`, `squash`, `rebase`), risquant d'introduire des commits de fusion synthétiques (`Merge branch '...' of ...`) polluant la lisibilité de l'historique et brisant la linéarité requise pour la traçabilité des spécifications et des correctifs.

## Décision
Nous décidons d'imposer une politique stricte d'historique linéaire et de fusion exclusivement par avance rapide (*fast-forward-only*) :

1. **Configuration du dépôt Forgejo (`nbt1/pere_noel_fremo`)** :
   - `allow_fast_forward_only_merge: true` : Autorise et impose le merge par avance rapide.
   - `default_merge_style: "fast-forward-only"` : Style de fusion configuré par défaut.
   - `allow_merge_commits: false` : Interdiction formelle de créer des commits de merge synthétiques à trois parents.
   - `allow_squash_merge: false` : Désactivation du squash pour préserver le découpage atomique des commits validés.
   - `allow_rebase: false` et `allow_rebase_explicit: false` : Désactivation de la réécriture de commits côté serveur lors du merge.
   - `allow_rebase_update: true` et `default_update_style: "rebase"` : Activation de la mise à jour assistée des PRs divergentes par rebase linéaire directement depuis l'interface Forgejo.
   - `default_delete_branch_after_merge: true` : Suppression automatique de la branche de travail après intégration pour préserver la propreté du dépôt.

2. **Défense en profondeur côté client Git local** :
   - Configuration locale de `pull.ff only` et `pull.rebase true` sur les clones de travail (`C:\data\dev\Python\pere_noel_fremo`) pour prévenir toute création accidentelle de merge commit lors des synchronisations.

3. **Workflow de contribution** :
   - Toute branche de fonctionnalité ou de correctif doit être strictement rebasée sur `master` avant résolution de la PR.
   - En cas d'évolution de `master`, la branche est synchronisée par rebase (`git rebase origin/master` ou via le bouton « Update branch by rebase » sur Forgejo).

## Conséquences
- **Historique linéaire immaculé** : Absence totale de commits de merge synthétiques.
- **Traçabilité simplifiée** : `git log` et `git bisect` déterministes et fidèles aux SHAs développés et testés.
- **Hygiène des branches** : Suppression automatisée des branches intégrées évitant l'accumulation de branches obsolètes sur Forgejo.
