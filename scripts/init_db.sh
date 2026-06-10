#!/bin/bash
# Créer les bases dev et test si elles n'existent pas
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    SELECT 'CREATE DATABASE hr_platform_dev'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'hr_platform_dev')\gexec
    SELECT 'CREATE DATABASE hr_platform_test'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'hr_platform_test')\gexec
EOSQL
