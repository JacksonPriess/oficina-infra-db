
def command(*args, payload=None):
    try:
        return subprocess.run(
            args, input=payload, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        # Nunca imprime stdin ou stdout: ambos podem conter Secrets completos.
        print(redact(f"Comando falhou (exit {error.returncode}): {' '.join(args)}"), file=sys.stderr)
        if error.stderr:
            print(redact(error.stderr), file=sys.stderr)
        raise


def kubectl(*args, payload=None):
    return command("kubectl", "-n", NAMESPACE, *args, payload=payload)


def apply(resource):
    kubectl("apply", "--server-side", "--field-manager=database-bootstrap", "-f", "-",
            payload=json.dumps(resource))


def secret(name, values):
    SENSITIVE_VALUES.update(values.values())
    apply({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name},
           "type": "Opaque", "data": {
               key: base64.b64encode(value.encode()).decode()
               for key, value in values.items()
           }})


def main():
    passwords = {key: os.environ.get(key, "")
                 for key in ("NUCLEO_DB_PASSWORD", "CATALOGO_DB_PASSWORD")}
    if any(not value or len(value) < 16 for value in passwords.values()):
        raise ValueError("Configure as duas senhas de aplicacao com pelo menos 16 caracteres.")
    if len(set(passwords.values())) != 2:
        raise ValueError("Use senhas diferentes para nucleo e catalogo.")

    command("aws", "rds", "wait", "db-instance-available", "--region", REGION,
            "--db-instance-identifier", "oficina-api-dev-postgres")
    instance = json.loads(command(
        "aws", "rds", "describe-db-instances", "--region", REGION,
        "--db-instance-identifier", "oficina-api-dev-postgres", "--output", "json",
    ))["DBInstances"][0]
    endpoint = instance["Endpoint"]
    admin = json.loads(json.loads(command(
        "aws", "secretsmanager", "get-secret-value", "--region", REGION,
        "--secret-id", instance["MasterUserSecret"]["SecretArn"], "--output", "json",
    ))["SecretString"])

    SENSITIVE_VALUES.add(admin["password"])

    applications = {
        "nucleo-database-secret": ("oficina_db", "nucleo_app", passwords["NUCLEO_DB_PASSWORD"]),
        "catalogo-produto-database-secret": (
            "oficina_produtos_db", "catalogo_produto_app", passwords["CATALOGO_DB_PASSWORD"]),
    }
    # Nao rotaciona senhas silenciosamente enquanto as aplicacoes estao em execucao.
    for name, (_, _, password) in applications.items():
        existing = kubectl("get", "secret", name, "--ignore-not-found", "-o", "json")
        if existing:
            stored = json.loads(existing)["data"].get("SPRING_DATASOURCE_PASSWORD", "")
            if base64.b64decode(stored).decode() != password:
                raise ValueError(f"Senha divergente em {name}. Rotacao exige procedimento separado.")

    kubectl("delete", "job", NAME, "--ignore-not-found", "--wait=true")
    try:
        secret(NAME, {
            "PGHOST": endpoint["Address"], "PGPORT": str(endpoint["Port"]),
            "PGUSER": admin["username"], "PGPASSWORD": admin["password"],
            "PGDATABASE": "postgres", "PGSSLMODE": "require", "PGCONNECT_TIMEOUT": "10",
            **passwords,
        })
        apply({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": NAME},
               "data": {filename: (ROOT / "bootstrap" / filename).read_text()
                        for filename in ("databases.sql", "run.sh")}})
        kubectl("apply", "-f", str(ROOT / "bootstrap" / "job.yaml"))
        kubectl("wait", "--for=condition=complete", f"job/{NAME}", "--timeout=360s")
        for name, (database, username, password) in applications.items():
            secret(name, {
                "SPRING_DATASOURCE_URL": (
                    f"jdbc:postgresql://{endpoint['Address']}:{endpoint['Port']}/{database}?sslmode=require"),
                "SPRING_DATASOURCE_USERNAME": username,
                "SPRING_DATASOURCE_PASSWORD": password,
            })
        print("Bootstrap concluido; Secrets separados das aplicacoes publicados no Kubernetes.")
    except subprocess.CalledProcessError:
        # Diagnostico do Job, com redacao das senhas inclusive em literais SQL.
        try:
            logs = kubectl("logs", f"job/{NAME}", "--tail=80", "--all-containers=true")
            print(redact(logs), file=sys.stderr)
        except subprocess.CalledProcessError:
            print("Logs do Job indisponiveis; coletando estado e eventos antes da limpeza.", file=sys.stderr)
        for diagnostic in (
                ("get", "pods", "-l", f"app={NAME}", "-o", "wide"),
                ("describe", "job", NAME),
                ("describe", "pods", "-l", f"app={NAME}")):
            try:
                print(redact(kubectl(*diagnostic)), file=sys.stderr)
            except subprocess.CalledProcessError:
                print(f"Diagnostico indisponivel: {' '.join(diagnostic)}", file=sys.stderr)
        raise
    finally:
        # Remove Pods antes de retirar a credencial administrativa temporaria.
        failure_in_progress = sys.exc_info()[0] is not None
        cleanup_error = None
        for resource in ("job", "secret", "configmap"):
            args = ("--wait=true",) if resource == "job" else ()
            try:
                kubectl("delete", resource, NAME, "--ignore-not-found", *args)
            except subprocess.CalledProcessError as error:
                cleanup_error = cleanup_error or error
                print(f"Falha ao remover {resource}/{NAME}; verifique a limpeza manual.", file=sys.stderr)
        if cleanup_error and not failure_in_progress:
            raise cleanup_error


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError:
        print("Falha no bootstrap. Consulte o comando e o erro detalhados acima.", file=sys.stderr)
        sys.exit(1)
    except (ValueError, KeyError) as error:
        print(f"Configuracao invalida: {error}", file=sys.stderr)