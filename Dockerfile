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

# Création de l'utilisateur non privilégié lutin et des répertoires de travail
RUN groupadd -g 1000 lutin && \
    useradd -u 1000 -g lutin -m lutin && \
    mkdir -p /app/res /app/logs && \
    chown -R lutin:lutin /app

# Exposition du port d'écoute FastAPI
EXPOSE 8000

# Exécution sous l'utilisateur non privilégié
USER lutin

# Commande par défaut pour lancer l'Espace Lutin
CMD ["pere-noel", "serve", "--host", "0.0.0.0", "--port", "8000", "--db-path", "/app/res/fremo.db"]
