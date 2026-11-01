#!/usr/bin/env bash
set -euo pipefail

# Aproxima o administrador RDS: CREATEDB/CREATEROLE, sem SUPERUSER real.
psql -X -w -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE dbadmin LOGIN CREATEDB CREATEROLE PASSWORD 'admin-test-only';
CREATE DATABASE oficina_db OWNER dbadmin;
SQL

export PGUSER=dbadmin
export PGPASSWORD=admin-test-only
export BOOTSTRAP_DIR="$PWD/bootstrap"
sh bootstrap/run.sh

# Regressao: o criador mantem ADMIN OPTION e pode herdar/assumir ambas as roles.
memberships=$(psql -X -w -At -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid WHERE m.member = current_user::regrole AND r.rolname IN ('nucleo_app', 'catalogo_produto_app') AND m.admin_option AND m.inherit_option AND m.set_option")
[ "$memberships" = 2 ]

# Prova que executar novamente nao apaga tabelas/dados das aplicacoes.
PGUSER=nucleo_app PGPASSWORD="$NUCLEO_DB_PASSWORD" PGDATABASE=oficina_db \
  psql -X -w -v ON_ERROR_STOP=1 -c 'CREATE TABLE public.bootstrap_existing_data (id integer); INSERT INTO public.bootstrap_existing_data VALUES (42);'
sh bootstrap/run.sh
result=$(PGUSER=nucleo_app PGPASSWORD="$NUCLEO_DB_PASSWORD" PGDATABASE=oficina_db \
  psql -X -w -At -v ON_ERROR_STOP=1 -c 'SELECT id FROM public.bootstrap_existing_data')
[ "$result" = 42 ]

# O administrador deve continuar acessando os dois bancos (consumidor Lambda atual).
PGDATABASE=oficina_db psql -X -w -v ON_ERROR_STOP=1 -c 'SELECT 1'
PGDATABASE=oficina_produtos_db psql -X -w -v ON_ERROR_STOP=1 -c 'SELECT 1'
echo 'Integracao PostgreSQL validada.'