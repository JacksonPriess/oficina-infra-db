#!/bin/sh
set -eu

psql -X -w -v ON_ERROR_STOP=1 -f "${BOOTSTRAP_DIR:-/bootstrap}/databases.sql"

# Testa autenticacao, criacao de objetos para o Flyway e rollback da verificacao.
PGUSER=nucleo_app PGPASSWORD="$NUCLEO_DB_PASSWORD" PGDATABASE=oficina_db \
  psql -X -w -v ON_ERROR_STOP=1 -c 'BEGIN; CREATE TABLE public.__bootstrap_permission_check (id integer); ROLLBACK;'
PGUSER=catalogo_produto_app PGPASSWORD="$CATALOGO_DB_PASSWORD" PGDATABASE=oficina_produtos_db \
  psql -X -w -v ON_ERROR_STOP=1 -c 'BEGIN; CREATE TABLE public.__bootstrap_permission_check (id integer); ROLLBACK;'

# Confirma que as credenciais validas nao permitem conectar ao banco vizinho.
if PGUSER=nucleo_app PGPASSWORD="$NUCLEO_DB_PASSWORD" PGDATABASE=oficina_produtos_db \
  psql -X -w -c 'SELECT 1' >/dev/null 2>&1; then
  echo 'ERRO: nucleo_app conseguiu acessar o banco do catalogo.'
  exit 1
fi
if PGUSER=catalogo_produto_app PGPASSWORD="$CATALOGO_DB_PASSWORD" PGDATABASE=oficina_db \
  psql -X -w -c 'SELECT 1' >/dev/null 2>&1; then
  echo 'ERRO: catalogo_produto_app conseguiu acessar o banco do nucleo.'
  exit 1
fi

echo 'Bancos, autenticacao, DDL e isolamento entre aplicacoes validados.'
