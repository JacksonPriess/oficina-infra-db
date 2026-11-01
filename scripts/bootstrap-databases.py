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
SENSITIVE_VALUES = set()


def redact(value):
    secrets = SENSITIVE_VALUES | {
        os.environ.get(key, "") for key in (
            "NUCLEO_DB_PASSWORD", "CATALOGO_DB_PASSWORD", "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
        )
    }
    representations = set()
    for secret_value in secrets - {""}:
        representations.update((secret_value, secret_value.replace("'", "''"),
                                json.dumps(secret_value)[1:-1],
                                base64.b64encode(secret_value.encode()).decode()))
    for representation in sorted(representations, key=len, reverse=True):
        value = value.replace(representation, "[REDACTED]")
    return value


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