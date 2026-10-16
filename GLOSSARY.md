# Le Père Noël de la Frémo

Organisation et tirage au sort annuel du Père Noël secret (Secret Santa) de la Frémo.

## Language

**Lutin**:
Membre participant au Père Noël secret, à la fois donneur d'un cadeau et bénéficiaire d'un autre lors d'une édition annuelle.
_Avoid_: User, personne, participant, player, compte

**Donneur**:
Lutin assigné pour préparer et offrir un cadeau à un autre Lutin.
_Avoid_: Offreur, expéditeur, source, giver

**Bénéficiaire**:
Lutin désigné pour recevoir le cadeau offert par un Donneur.
_Avoid_: Receveur, destinataire, cible, gifted

**Tirage au sort**:
Processus d'affectation associant chaque Donneur à un unique Bénéficiaire distinct selon les contraintes de l'édition.
_Avoid_: Matching, shuffle, tossing, attribution

**Cheater**:
Association Donneur-Bénéficiaire prédéfinie imposée manuellement lors du tirage au sort.
_Avoid_: Attribution forcée, triche, override, cheat

**Exclusion**:
Interdiction formelle pour un Donneur d'offrir un cadeau à un Lutin désigné (ex. couple ou famille).
_Avoid_: Blacklist, restriction, veto

**Historique**:
Liste exhaustive et permanente de tous les Bénéficiaires reçus par un Donneur lors des millésimes strictement antérieurs à l'Édition considérée, interdisant définitivement leur réattribution. Une Attribution millésimée d'une Édition ultérieure n'en fait jamais partie.
_Avoid_: Antécédents, mémoire, historique glissant

**Édition**:
Itération annuelle du Père Noël secret désignée par son millésime (`year`), progressant à travers un cycle d'états (`draft` -> `announced` -> `drawn` -> `revealed`) dont le module `edition` est l'unique propriétaire. L'**Annonce** fait passer `draft` à `announced` (au premier envoi réussi, jamais en simulation) ; le **Tirage au sort** fait passer à `drawn` (scellement, rejouable uniquement par `--force-retirage`) ; la **Révélation** fait passer `drawn` à `revealed`. Une Édition est « scellée » dès `drawn` : présences verrouillées et Bénéficiaires consultables.
_Avoid_: Campagne (au sens d'Édition ; voir **Campagne**), saison, tournoi, session

**Repas de Noël**:
Rassemblement rituel annuel réunissant les Lutins pour célébrer le Père Noël secret, au cours duquel le vainqueur du Défi du lutin ouvre son cadeau en premier avant la distribution des cadeaux.
_Avoid_: Fête, fête de Noël, événement, soirée, party, banquet

**Attribution millésimée**:
Association immuable entre un Donneur et son Bénéficiaire scellée pour une Édition précise (`year`), historiquement issue d'un tirage au sort annuel.
_Avoid_: Paire, matching, assignation, record

**Reconstitution historique**:
Opération de migration programmatique et idempotente restaurant l'historique complet des Attributions millésimées (2014-2025) à partir des instantanés d'archives YAML, scellant les éditions passées sans écraser l'édition courante.
_Avoid_: Backfill manuel, injection SQL, bricolage d'historique



**Absent**:
Lutin répertorié dans la base mais exclu de la participation pour l'édition courante.
_Avoid_: Désinscrit, ignoré, skipped

**Annonce**:
Courriel officiel lançant l'édition annuelle, transmettant à chaque Lutin son Lien magique pour accéder à son Espace Lutin, initier la Confirmation de présence et ouvrir le Défi du lutin avant la réalisation du Tirage au sort. Doit respecter les standards d'e-mailing HTML « bulletproof » (couleurs de fond de repli `bgcolor` et `background-color` strictes sous les dégradés CSS, bouton CTA sous forme de table dédiée, et support dual-scheme du mode sombre) pour garantir un rendu parfait sur l'ensemble des clients de messagerie (Outlook Web/Desktop, Gmail, Apple Mail).
_Avoid_: Teaser, invitation, notification

**Révélation**:
Courriel officiel notifiant les Lutins que le Tirage au sort a été réalisé, les invitant à se reconnecter à leur Espace Lutin via leur Lien magique pour dévoiler leur Bénéficiaire sous la Carte à gratter, et faisant basculer l'Édition au statut `revealed`.
_Avoid_: Découverte, déblocage, notification de tirage, alerte

**Campagne**:
Envoi groupé d'un courriel officiel, Annonce ou Révélation, à un ensemble de Lutins, porté par le module `campagne` (boucle d'envoi unique et port d'envoi `Expediteur`). Une Campagne n'est jamais une Édition : elle se déroule au sein d'une Édition et peut la faire avancer (Annonce : `draft` -> `announced`, Révélation : `drawn` -> `revealed`).
_Avoid_: Édition, mailing, newsletter

**Lien magique**:
URL unique et sécurisée transmise à un Lutin pour lui donner un accès direct à son Espace Lutin sans nécessiter de mot de passe.
_Avoid_: Token link, magic URL, jeton

**Espace Lutin**:
Page web individuelle et confidentielle dédiée à un Lutin pour confirmer sa présence, relever le défi et consulter son Bénéficiaire.
_Avoid_: Dashboard, portail, profil, compte

**Confirmation de présence**:
Action par laquelle un Lutin valide ou décline sa participation à l'édition courante en réponse à l'Annonce.
_Avoid_: RSVP, inscription, check-in, vote

**Défi du lutin**:
Compétition rituelle annuelle (alternant entre défi créatif et série de logigrammes hebdomadaires) disputée sous forme de championnat à points permettant de départager les Lutins et de désigner le vainqueur qui ouvrira son cadeau en premier lors du Repas de Noël.
_Avoid_: Défi de la luge, quiz, challenge, mini-jeu, concours

**Manche**:
Épreuve bi-hebdomadaire du Défi du lutin associée à une Grille logique débloquée à date fixe, sur laquelle chaque Lutin dispose d'un parcours chronométré unique limité à 3 soumissions de validation avec pénalité de temps pour marquer des points de championnat.
_Avoid_: Round, niveau, étape, session

**Soumission**:
Tentative de validation complète de la Grille logique transmise par un Lutin au cours d'une Manche, plafonnée à 3 essais par manche et assortie d'une pénalité de temps en cas d'erreur précédant la résolution.
_Avoid_: Requête de solve, validation partielle, essai non décompté, tentative infinie

**Parcours de manche**:
Déroulé chronométré unique d'un Lutin sur une Manche, du démarrage à la résolution, l'abandon ou le scellement après 3 Soumissions.
_Avoid_: session, run, tentative

**Grille logique**:
Casse-tête de déduction à indices croisés proposé lors d'une Manche du Défi du lutin, chronométré pour établir le classement de la manche.
_Avoid_: Logigramme, puzzle d'Einstein, énigme

**Pseudo de lutin**:
Pseudonyme festif et humoristique attribué aléatoirement à chaque Lutin sur le tableau des scores public pour préserver le secret de l'identité du vainqueur jusqu'au Repas de Noël.
_Avoid_: Pseudo de lugeur, alias, handle, avatar

**Admin aveugle**:
Mode d'administration masquant les attributions de cadeaux à l'organisateur pour préserver sa propre surprise, tout en conservant une traçabilité exploitable par un agent.
_Avoid_: Mode discret, blind mode, masquage

**Carte à gratter**:
Composant interactif virtuel sur l'Espace Lutin permettant à un Donneur de dévoiler l'identité de son Bénéficiaire après la réalisation du tirage au sort.
_Avoid_: Scratchcard, révélation immédiate, popup

**Tableau des scores**:
Classement rituel public affichant en permanence les points et les temps du championnat du Défi du lutin sous les Pseudos de lutin pour désigner le vainqueur qui ouvrira son cadeau en premier.
_Avoid_: Leaderboard, ranking, palmarès
