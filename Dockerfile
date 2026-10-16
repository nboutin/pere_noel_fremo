FROM python:3.12-slim

# Force le flush stdout et désactive la création de fichiers .pyc
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FREMO_RES_DIR=/app/res

WORKDIR /app

# Dependances : versions exactes issues de uv.lock (build reproductible)
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.12.10 &&     uv export --frozen --no-dev --no-emit-project --no-hashes -o requirements.lock &&     pip install --no-cache-dir -r requirements.lock &&     pip uninstall -y uv

# Installation du package pere-noel-fremo (sans re-resoudre les dependances)
COPY source/ ./source/
RUN pip install --no-cache-dir --no-deps .

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
