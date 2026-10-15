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
