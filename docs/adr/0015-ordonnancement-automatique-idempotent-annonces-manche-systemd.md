# 0015. Ordonnancement automatique et idempotence des Annonces de manche via Systemd Timer

Date: 2026-10-19

## Statut
Accepté

## Contexte
Le championnat bi-hebdomadaire du Défi du lutin (ADR-0007) requiert l'envoi de 15 courriels d'Annonce de manche (ADR-0014), débloqués successivement tous les lundis et vendredis à 17h00.
Déclencher manuellement ces 13 prochaines campagnes impose une contrainte de disponibilité à l'organisateur et présente un risque d'oubli ou de décalage.
L'automatisation doit s'intégrer harmonieusement sur l'hôte Debian du Homelab (`homelab-admin`), garantir une idempotence absolue (aucun double envoi possible même en cas de réexécution ou de redémarrage), et traiter gracieusement les coupures éventuelles sans saturer les boîtes de réception des participants.

## Décision

1. **Table d'idempotence SQLite (`campagnes_manches`)** :
   - Ajout d'une table dédiée dans `res/fremo.db` :
     ```sql
     CREATE TABLE IF NOT EXISTS campagnes_manches (
         year INTEGER NOT NULL,
         manche_id INTEGER NOT NULL,
         sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
         count_sent INTEGER NOT NULL,
         PRIMARY KEY (year, manche_id)
     );
     ```
   - Migration automatique et idempotente dans `init_db()`.
   - Initialisation pour l'Édition 2026 : les Manches 1 et 2 sont insérées d'emblée comme déjà expédiées pour sanctuariser le passé.

2. **Mode de détection dynamique automatique (`--auto`)** :
   - Ajout du flag `--auto` sur la commande `pere-noel annonce-manche`.
   - Lorsque `--auto` est actif :
     - La commande détermine l'instant courant en heure locale de Paris (`Europe/Paris`).
     - Elle identifie les manches dont la date `unlock_at` est échue (`unlock_at <= now`).
     - Elle filtre les manches déjà consignées dans `campagnes_manches`.
     - Si aucune manche éligible n'attend d'envoi, elle termine en succès immédiat (code retour 0, message d'inactivité).
     - **Fenêtre de rattrapage (Lookback window)** : en cas d'indisponibilité prolongée du serveur, seule la manche la plus récemment déverrouillée (déblocage intervenu dans les dernières 72 heures) est expédiée, évitant les envois multiples intempestifs.
     - À l'issue d'un envoi nominal sans échec, la manche est enregistrée dans `campagnes_manches`.

3. **Ordonnancement hôte via Systemd Timer (`homelab-admin`)** :
   - Création d'une unité de service et d'un timer systemd sur l'hôte Debian :
     - `/etc/systemd/system/pere-noel-manches.service` : exécute `docker exec pere_noel_fremo pere-noel annonce-manche --auto`.
     - `/etc/systemd/system/pere-noel-manches.timer` : cadence le déclenchement chaque lundi et vendredi à 17h01 (`OnCalendar=Mon,Fri *-*-* 17:01:00`).
   - Le délai d'une minute (17h01) garantit que la condition temporelle `unlock_at <= now` (17h00) est toujours strictement satisfaite au moment de l'exécution.
   - Les journaux d'exécution sont consultables nativement via `journalctl -u pere-noel-manches`.

## Conséquences
- Automatisation complète, ponctuelle et transparente des 13 prochaines ouvertures de manche.
- Robustesse totale face aux redémarrages et coupures d'électricité du Homelab.
- Zéro surcharge mémoire sur le conteneur FastAPI (pas de boucle d'attente ni de thread démon permanent).
