# Hébergement sur Homelab et exposition publique via Tailscale Funnel

## Contexte
L'Espace Lutin doit être accessible en HTTPS public pour que les Lutins puissent se connecter sans installer de VPN ni créer de compte, via le Lien magique reçu par courriel d'Annonce. L'organisateur dispose d'un Homelab fonctionnant 24h/24 avec Dockge et d'un nœud Tailscale déjà configuré avec Tailscale Funnel actif (`homelab.tail7d8b91.ts.net`), mais ne possède pas de compte Cloudflare ni de nom de domaine dédié.

## Décision
1. **Hébergement et orchestration** : L'Espace Lutin est déployé sous forme de conteneur Docker orchestré par Dockge dans `/opt/stacks/pere_noel_fremo` sur le Homelab.
2. **Persistance et port local** : Le répertoire `res/` (contenant la base SQLite `res/fremo.db`) est monté en volume persistant. Le serveur web écoute sur le port `8000` de l'hôte (`8000:8000`).
3. **Exposition publique (Tailscale Funnel)** : Le service est exposé publiquement sur Internet sans ouverture de port de box ni achat de domaine via Tailscale Funnel sur le port 10000 : `https://homelab.tail7d8b91.ts.net:10000`.
4. **Base URL** : L'URL racine permanente configurée dans `res/secure_data.yml` pour forger les Liens magiques est fixée à `https://homelab.tail7d8b91.ts.net:10000`.
5. **Centralisation de l'administration** : Les commandes CLI d'administration (`pere-noel annonce`, `pere-noel tirage`, audit) sont exécutées directement sur le Homelab accédant à `res/fremo.db`.
