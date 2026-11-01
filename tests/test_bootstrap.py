import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "bootstrap", Path(__file__).resolve().parents[1] / "scripts/bootstrap-databases.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "NUCLEO_DB_PASSWORD": "nucleo-test-password-1234",
            "CATALOGO_DB_PASSWORD": "catalogo-test-password-5678",
        })
        sensitive_values = patch.object(bootstrap, "SENSITIVE_VALUES", set())
        sensitive_values.start()
        self.addCleanup(sensitive_values.stop)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.resources = []
        self.calls = []

    def aws(self, *args, **kwargs):
        if "describe-db-instances" in args:
            return json.dumps({"DBInstances": [{
                "Endpoint": {"Address": "private-rds.example", "Port": 5432},
                "MasterUserSecret": {"SecretArn": "arn:test"},
            }]})
        if "get-secret-value" in args:
            return json.dumps({"SecretString": json.dumps({
                "username": "dbadmin", "password": "administrative-test-secret"})})
        return ""

    def kube(self, *args, payload=None):
        self.calls.append(args)
        if payload:
            self.resources.append(json.loads(payload))
        return ""

    def test_success_publishes_independent_credentials_and_removes_admin_secret(self):
        with patch.object(bootstrap, "command", side_effect=self.aws), \
                patch.object(bootstrap, "kubectl", side_effect=self.kube):
            bootstrap.main()
        secrets = {r["metadata"]["name"]: r["data"] for r in self.resources if r["kind"] == "Secret"}
        for name, database, username in (
                ("nucleo-database-secret", "oficina_db", "nucleo_app"),
                ("catalogo-produto-database-secret", "oficina_produtos_db", "catalogo_produto_app")):
            values = {key: base64.b64decode(value).decode() for key, value in secrets[name].items()}
            self.assertEqual(username, values["SPRING_DATASOURCE_USERNAME"])
            self.assertIn(f"/{database}?sslmode=require", values["SPRING_DATASOURCE_URL"])
            self.assertNotIn("administrative-test-secret", values.values())
        self.assertIn(("delete", "secret", bootstrap.NAME, "--ignore-not-found"), self.calls)

    def test_command_reports_stderr_but_redacts_passwords_and_ignores_stdout(self):
        password = "password-with-'quote-1234"
        bootstrap.SENSITIVE_VALUES.add(password)
        encoded = base64.b64encode(password.encode()).decode()
        error = subprocess.CalledProcessError(
            1, ["kubectl"], output="SECRET-STDOUT-MUST-NOT-BE-PRINTED",
            stderr=f"Forbidden: {password} {password.replace(chr(39), chr(39) * 2)} {encoded}")
        stderr = io.StringIO()
        with patch.object(bootstrap.subprocess, "run", side_effect=error), patch("sys.stderr", stderr):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                bootstrap.command("kubectl", "apply", "-f", "-", payload="SECRET-STDIN")
        self.assertIs(error, raised.exception)
        self.assertIn("kubectl apply -f -", stderr.getvalue())
        self.assertIn("Forbidden", stderr.getvalue())
        for sensitive in (password, encoded, "SECRET-STDOUT-MUST-NOT-BE-PRINTED", "SECRET-STDIN"):
            self.assertNotIn(sensitive, stderr.getvalue())

    def test_cleanup_failures_preserve_original_error_and_attempt_secret_removal(self):
        original = subprocess.CalledProcessError(1, "wait")
        failed = False

        def kube(*args, **kwargs):
            nonlocal failed
            if args[0] == "wait":
                failed = True
                raise original
            self.calls.append(args)
            if failed and args[:2] == ("delete", "job"):
                raise subprocess.CalledProcessError(1, "cleanup")
            return ""

        with patch.object(bootstrap, "command", side_effect=self.aws), \
                patch.object(bootstrap, "kubectl", side_effect=kube), patch("sys.stderr", io.StringIO()):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                bootstrap.main()
        self.assertIs(original, raised.exception)
        self.assertIn(("delete", "secret", bootstrap.NAME, "--ignore-not-found"), self.calls)
        self.assertIn(("describe", "job", bootstrap.NAME), self.calls)

    def test_missing_password_fails_before_accessing_aws(self):
        with patch.dict(os.environ, {"NUCLEO_DB_PASSWORD": ""}), \
                patch.object(bootstrap, "command") as command:
            with self.assertRaises(ValueError):
                bootstrap.main()
            command.assert_not_called()

    def test_equal_passwords_are_rejected(self):
        with patch.dict(os.environ, {"CATALOGO_DB_PASSWORD": os.environ["NUCLEO_DB_PASSWORD"]}), \
                patch.object(bootstrap, "command") as command:
            with self.assertRaises(ValueError):
                bootstrap.main()
            command.assert_not_called()

    def test_conflicting_existing_password_does_not_run_job(self):
        old = base64.b64encode(b"different-password").decode()
        with patch.object(bootstrap, "command", side_effect=self.aws), \
                patch.object(bootstrap, "kubectl", return_value=json.dumps({
                    "data": {"SPRING_DATASOURCE_PASSWORD": old}})) as kube:
            with self.assertRaises(ValueError):
                bootstrap.main()
        self.assertTrue(all(call.args[0] == "get" for call in kube.call_args_list))

    def test_job_failure_cleans_admin_secret_without_publishing_app_credentials(self):
        def fail_wait(*args, **kwargs):
            if args[0] == "wait":
                raise subprocess.CalledProcessError(1, "kubectl")
            if args[0] == "logs":
                return "administrative-test-secret " + os.environ["NUCLEO_DB_PASSWORD"]
            return self.kube(*args, **kwargs)

        stderr = io.StringIO()
        with patch.object(bootstrap, "command", side_effect=self.aws), \
                patch.object(bootstrap, "kubectl", side_effect=fail_wait), patch("sys.stderr", stderr):
            with self.assertRaises(subprocess.CalledProcessError):
                bootstrap.main()
        secret_names = [r["metadata"]["name"] for r in self.resources if r["kind"] == "Secret"]
        self.assertEqual([bootstrap.NAME], secret_names)
        self.assertNotIn("administrative-test-secret", stderr.getvalue())
        self.assertNotIn(os.environ["NUCLEO_DB_PASSWORD"], stderr.getvalue())
        self.assertIn("[REDACTED]", stderr.getvalue())
        self.assertIn(("delete", "secret", bootstrap.NAME, "--ignore-not-found"), self.calls)


if __name__ == "__main__":
    unittest.main()
