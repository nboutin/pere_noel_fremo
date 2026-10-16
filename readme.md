# README

## Dependencies

    uv sync --extra dev          # cree .venv depuis uv.lock (recommande)
    # ou : python -m venv .venv && .venv/bin/pip install -e .[dev]

Le verrou `uv.lock` est suivi dans git ; l'image Docker installe ces versions exactes.
Apres modification des dependances : `uv lock`, puis `uv lock --check` pour verifier.

## Tests

    pytest    # affiche la couverture et echoue sous le seuil (--cov-fail-under)

## Email annonce

* Add res/secure_data.yml
* Add res/code_secret_client.apps.googleusercontent.com.json

## Espace Admin

L'Espace Admin est une application distincte de l'Espace Lutin, sur son propre listener (ADR-0009 §5, ADR-0013 §4) :

| Service compose | Commande | Port loopback | Exposition |
| --- | --- | --- | --- |
| `pere_noel_fremo` | `pere-noel serve` | `127.0.0.1:8000` | Funnel `:10000` (public) |
| `pere_noel_fremo_admin` | `pere-noel serve-admin` (port 8001 par défaut) | `127.0.0.1:8001` | `tailscale serve` seulement |

L'application publique ne contient aucune route `/admin*`. Le cookie de session est toujours `Secure` : l'accès se fait en
HTTPS via Tailscale, à l'adresse `https://homelab.tail7d8b91.ts.net:8444/admin` (publication :
`tailscale serve --bg --https=8444 http://127.0.0.1:8001`). Toute requête portant l'en-tête `Tailscale-Funnel-Request: ?1`
reçoit un 404.

Deux clés dans `res/secure_data.yml`, ou les variables d'environnement correspondantes (prioritaires) :

| Clé YAML | Variable | Rôle |
| --- | --- | --- |
| `admin_password` | `ADMIN_PASSWORD` | Mot de passe de connexion à `/admin` |
| `admin_session_secret` | `ADMIN_SESSION_SECRET` | Secret de signature du cookie de session (32 octets minimum) |

Sans `admin_session_secret` valide (absent, vide ou de moins de 32 octets), l'Espace Admin est désactivé :
`/admin` et `/admin/*` répondent le même 404 que les routes inconnues, et un avertissement est journalisé au démarrage.
Générer un secret :

    python -c "import secrets; print(secrets.token_urlsafe(48))"

## Generate credentials.json

Go to the Google Cloud Console.
Navigate to the "APIs & Services" > "Credentials" page.
Create or select an existing OAuth 2.0 Client ID.
Download the credentials.json file.
Place the downloaded credentials.json file in the res directory of your project.

## Google Cloud API

- https://console.cloud.google.com
- https://developers.google.com/gmail/api/quickstart/python

## Troubleshooting

1. Delete token.json to re-new authentication
