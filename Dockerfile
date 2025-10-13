# Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

# Installer build deps nécessaires pour psycopg2 si utilisé
RUN apt-get update && \
    apt-get install -y gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copier le code
COPY . /app

# Ne pas exposer secrets ici; .env sur l'hôte
EXPOSE 5000

# Lancer le fichier principal (adapte si votre app est un module)
CMD ["python", "app/app.py"]
