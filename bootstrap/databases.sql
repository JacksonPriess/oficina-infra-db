\set ON_ERROR_STOP on
\getenv nucleo_password NUCLEO_DB_PASSWORD
\getenv catalogo_password CATALOGO_DB_PASSWORD
SELECT current_user AS bootstrap_admin \gset

-- Roles de aplicacao nao podem criar bancos, roles ou ignorar permissoes.
SELECT 'CREATE ROLE nucleo_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'nucleo_app') \gexec
SELECT 'CREATE ROLE catalogo_produto_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'catalogo_produto_app') \gexec

-- O criador ja recebe ADMIN OPTION; aqui habilitamos apenas INHERIT e SET.
GRANT nucleo_app, catalogo_produto_app TO :"bootstrap_admin" WITH INHERIT TRUE, SET TRUE;
-- Falha se uma role preexistente foi elevada fora deste procedimento.
DO $$
BEGIN
    IF EXISTS (
        SELECT FROM pg_roles
        WHERE rolname IN ('nucleo_app', 'catalogo_produto_app')
          AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'Role de aplicacao possui privilegios administrativos inesperados';
    END IF;
END;
$$;
SELECT format('ALTER ROLE nucleo_app PASSWORD %L', :'nucleo_password') \gexec
SELECT format('ALTER ROLE catalogo_produto_app PASSWORD %L', :'catalogo_password') \gexec

-- CREATE DATABASE precisa executar fora de uma transacao.
SELECT 'CREATE DATABASE oficina_db OWNER nucleo_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'oficina_db') \gexec
SELECT 'CREATE DATABASE oficina_produtos_db OWNER catalogo_produto_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'oficina_produtos_db') \gexec
ALTER DATABASE oficina_db OWNER TO nucleo_app;
ALTER DATABASE oficina_produtos_db OWNER TO catalogo_produto_app;

REVOKE ALL ON DATABASE oficina_db FROM PUBLIC, catalogo_produto_app;
REVOKE ALL ON DATABASE oficina_produtos_db FROM PUBLIC, nucleo_app;
GRANT CONNECT, CREATE, TEMPORARY ON DATABASE oficina_db TO nucleo_app;
GRANT CONNECT, CREATE, TEMPORARY ON DATABASE oficina_produtos_db TO catalogo_produto_app;

-- Detecta tambem acesso herdado de memberships preexistentes.
DO $$
BEGIN
    IF has_database_privilege('nucleo_app', 'oficina_produtos_db', 'CONNECT')
       OR has_database_privilege('catalogo_produto_app', 'oficina_db', 'CONNECT') THEN
        RAISE EXCEPTION 'Acesso cruzado entre bancos de aplicacao detectado';
    END IF;
END;
$$;

\connect oficina_db
ALTER SCHEMA public OWNER TO nucleo_app;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO nucleo_app;

\connect oficina_produtos_db
ALTER SCHEMA public OWNER TO catalogo_produto_app;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO catalogo_produto_app;
