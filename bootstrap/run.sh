#!/bin/sh
set -eu

psql -X -w -v ON_ERROR_STOP=1 -f "${BOOTSTRAP_DIR:-/bootstrap}/databases.sql"

# Testa autenticacao, criacao de objetos para o Flyway e rollback da verificacao.
PGUSER=nucleo_app PGPASSWORD="$NUCLEO_DB_PASSWORD" PGDATABASE=oficina_db \
  psql -X -w -v ON_ERROR_STOP=1 -c 'BEGIN; CREATE TABLE public.__bootstrap_permission_check (id integer); ROLLBACK;'
PGUSER=catalogo_produto_app PGPASSWORD="$CATALOGO_DB_PASSWORD" PGDATABASE=oficina_produtos_db \
  psql -X -w -v ON_ERROR_STOP=1 -c 'BEGIN; CREATE TABLE public.__bootstrap_permission_check (id integer); ROLLBACK;'

PGUSER=financeiro_app PGPASSWORD="$FINANCEIRO_DB_PASSWORD" PGDATABASE=oficina_financeiro_db \
  psql -X -w -v ON_ERROR_STOP=1 -c 'BEGIN; CREATE TABLE public.__bootstrap_permission_check (id integer); ROLLBACK;'

# Confirma que as credenciais validas nao permitem conectar aos outros bancos.
check_denied() {
  if PGUSER="$1" PGPASSWORD="$2" PGDATABASE="$3" \
    psql -X -w -c 'SELECT 1' >/dev/null 2>&1; then
    echo "ERRO: $1 conseguiu acessar $3."
    exit 1
  fi
}

check_denied nucleo_app "$NUCLEO_DB_PASSWORD" oficina_produtos_db
check_denied nucleo_app "$NUCLEO_DB_PASSWORD" oficina_financeiro_db
check_denied catalogo_produto_app "$CATALOGO_DB_PASSWORD" oficina_db
check_denied catalogo_produto_app "$CATALOGO_DB_PASSWORD" oficina_financeiro_db
check_denied financeiro_app "$FINANCEIRO_DB_PASSWORD" oficina_db
check_denied financeiro_app "$FINANCEIRO_DB_PASSWORD" oficina_produtos_db

echo 'Bancos, autenticacao, DDL e isolamento entre aplicacoes validados.'
