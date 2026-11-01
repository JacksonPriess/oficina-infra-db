#!/usr/bin/env python3
"""Provisiona bancos dentro da VPC, sem colocar senhas em argumentos ou arquivos."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = os.environ.get("K8S_NAMESPACE", "default")
REGION = os.environ.get("AWS_REGION", "us-east-1")
NAME = "oficina-database-bootstrap"


def command(*args, payload=None):
    return subprocess.run(
        args, input=payload, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=True,
    ).stdout


def kubectl(*args, payload=None):
    return command("kubectl", "-n", NAMESPACE, *args, payload=payload)


def apply(resource):
    kubectl("apply", "--server-side", "--field-manager=database-bootstrap", "-f", "-",
            payload=json.dumps(resource))


def secret(name, values):
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
            for password in (*passwords.values(), admin["password"]):
                for representation in (password.replace("'", "''"), password):
                    logs = logs.replace(representation, "[REDACTED]")
            print(logs, file=sys.stderr)
        except subprocess.CalledProcessError:
            print("Logs do Job indisponiveis; verifique os eventos do Kubernetes.", file=sys.stderr)
        raise
    finally:
        # Remove Pods antes de retirar a credencial administrativa temporaria.
        kubectl("delete", "job", NAME, "--ignore-not-found", "--wait=true")
        kubectl("delete", "secret", NAME, "--ignore-not-found")
        kubectl("delete", "configmap", NAME, "--ignore-not-found")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError:
        # Nao imprime stdout/stderr de comandos que possam carregar credenciais.
        print("Falha no bootstrap. Verifique RDS, acesso ao EKS, Secrets e permissoes AWS.", file=sys.stderr)
        sys.exit(1)
    except (ValueError, KeyError) as error:
        print(f"Configuracao invalida: {error}", file=sys.stderr)
        sys.exit(1)
