FROM python:3.12-slim

# Force le flush stdout et désactive la création de fichiers .pyc
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FREMO_RES_DIR=/app/res

WORKDIR /app

# Copie des fichiers de configuration et du code source
COPY pyproject.toml .
COPY source/ ./source/

# Installation du package pere-noel-fremo en mode production
RUN pip install --no-cache-dir .

# Création du répertoire de données persistant pour le montage du volume
RUN mkdir -p /app/res

# Exposition du port d'écoute FastAPI
EXPOSE 8000

# Commande par défaut pour lancer l'Espace Lutin
CMD ["pere-noel", "serve", "--host", "0.0.0.0", "--port", "8000", "--db-path", "/app/res/fremo.db"]
