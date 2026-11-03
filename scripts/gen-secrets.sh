#!/bin/sh
# Genera .env a partir de .env.example con secretos aleatorios. No sobrescribe un .env existente.
set -e
cd "$(dirname "$0")/.."
[ -f .env ] && { echo ".env ya existe; no se modifica."; exit 0; }
rnd() { python3 -c "import secrets;print(secrets.token_urlsafe($1))" 2>/dev/null || openssl rand -base64 "$1" | tr -d '=+/\n'; }
fernet() { python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())" 2>/dev/null || openssl rand -base64 32 | tr '+/' '-_'; }
cp .env.example .env
for k in POSTGRES_SUPERUSER_PASSWORD RADAR_DB_PASSWORD N8N_DB_PASSWORD LANGFLOW_DB_PASSWORD RADAR_SERVICE_KEY N8N_ENCRYPTION_KEY LANGFLOW_SUPERUSER_PASSWORD; do
  sed -i "s|^$k=.*|$k=$(rnd 24)|" .env
done
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(rnd 48)|" .env
sed -i "s|^FERNET_KEY=.*|FERNET_KEY=$(fernet)|" .env
echo ".env generado con secretos aleatorios."
