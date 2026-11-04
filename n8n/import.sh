#!/bin/sh
# Importa credenciales y workflows en n8n al levantar el stack (servicio de una sola ejecución `n8n-import`).
# Las credenciales se generan desde variables de entorno: el JSON versionado no contiene secretos.
set -e

cat > /tmp/credentials.json <<EOF
[
  {
    "id": "radarN8nDb",
    "name": "PostgreSQL de n8n (registro propio)",
    "type": "postgres",
    "data": {
      "host": "${DB_POSTGRESDB_HOST}",
      "port": 5432,
      "database": "${DB_POSTGRESDB_DATABASE}",
      "user": "${DB_POSTGRESDB_USER}",
      "password": "${DB_POSTGRESDB_PASSWORD}",
      "ssl": "disable",
      "allowUnauthorizedCerts": false,
      "maxConnections": 5
    }
  }
]
EOF

# Reintentos: n8n puede tardar unos segundos en dejar lista su clave de cifrado en una instalación nueva.
ok=0
for i in 1 2 3 4 5 6; do
  if n8n import:credentials --input=/tmp/credentials.json; then ok=1; break; fi
  echo "Reintentando la importación de credenciales ($i/6)..."; sleep 5
done
[ "$ok" = 1 ] || { echo "No se pudieron importar las credenciales"; exit 1; }
rm -f /tmp/credentials.json
n8n import:workflow --separate --input=/workflows
# El flujo diario queda publicado (cron y webhook activos) al arrancar n8n.
n8n publish:workflow --id=RadarDiario01
echo "Workflows importados."
