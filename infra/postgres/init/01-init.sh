#!/bin/bash
# Crea tres bases aisladas, cada una con su propio rol. n8n y LangFlow NO tienen acceso a la base radar.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE radar_app LOGIN PASSWORD '${RADAR_DB_PASSWORD}';
CREATE ROLE n8n       LOGIN PASSWORD '${N8N_DB_PASSWORD}';
CREATE ROLE langflow  LOGIN PASSWORD '${LANGFLOW_DB_PASSWORD}';
CREATE DATABASE radar     OWNER radar_app;
CREATE DATABASE n8n       OWNER n8n;
CREATE DATABASE langflow  OWNER langflow;
REVOKE ALL ON DATABASE radar    FROM PUBLIC;
REVOKE ALL ON DATABASE n8n      FROM PUBLIC;
REVOKE ALL ON DATABASE langflow FROM PUBLIC;
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname radar -c 'CREATE EXTENSION IF NOT EXISTS citext;'
