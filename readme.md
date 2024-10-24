# README

## Dependencies

    pip install --upgrade --user -r requirements.txt

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
