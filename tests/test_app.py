"""Integration tests for the local financial application, using only Python's stdlib.

Run from the project directory with ``python3 -m unittest discover -s tests -v``.
Each test uses its own on-disk database and a real HTTP server subprocess.
"""

from __future__ import annotations

import csv
import http.client
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class AssetReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.references.append(("js", attrs["src"]))
        elif tag == "link" and "stylesheet" in attrs.get("rel", "").split():
            self.references.append(("css", attrs["href"]))


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="financiero-test-")
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"
        self.data_dir.mkdir()
        self.log_file = (Path(self.temp.name) / "server.log").open("w+")
        self.addCleanup(self.log_file.close)
        self.process = None
        self.addCleanup(self.stop_server)
        self.start_server()

    def start_server(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.process = subprocess.Popen(
            [sys.executable, str(PROJECT / "app.py"),
             "--data-dir", str(self.data_dir), "--port", str(self.port)],
            cwd=PROJECT,
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.fail("Application exited during startup:\n" + self.server_log())
            try:
                status, _, _ = self.request("GET", "/api/data?month=2030-01")
                if status == 200:
                    return
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.05)
        self.fail("Application did not become ready:\n" + self.server_log())

    def server_log(self):
        self.log_file.flush()
        self.log_file.seek(0)
        return self.log_file.read()

    def stop_server(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            self.process = None

    def request(self, method, path, payload=None, headers=None):
        request_headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=request_headers)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def json_request(self, method, path, payload=None, expected=200, headers=None):
        status, response_headers, raw = self.request(method, path, payload, headers)
        self.assertEqual(status, expected, raw.decode("utf-8", errors="replace"))
        self.assertIn("application/json", response_headers.get("Content-Type", ""))
        return json.loads(raw)

    def transaction(self, **overrides):
        value = {
            "type": "expense", "amount_cents": 1299, "description": "Compra semanal",
            "category": "food", "date": "2030-05-12",
        }
        value.update(overrides)
        return value

    def create(self, **overrides):
        payload = self.transaction(**overrides)
        result = self.json_request("POST", "/api/transactions", payload, expected=201)
        transaction = result["transaction"]
        self.assertTrue(transaction["id"])
        for key, value in payload.items():
            self.assertEqual(transaction[key], value)
        return transaction

    def test_empty_database_and_front_page(self):
        data = self.json_request("GET", "/api/data?month=2030-05")
        self.assertEqual(data["month"], "2030-05")
        self.assertEqual(data["transactions"], [])
        self.assertEqual(data["breakdown"], [])
        self.assertEqual(data["summary"], {
            "income_cents": 0, "expense_cents": 0, "balance_cents": 0,
            "total_balance_cents": 0, "transaction_count": 0,
        })
        self.assertIn("food", {row["id"] for row in data["categories"]["expense"]})
        self.assertIn("salary", {row["id"] for row in data["categories"]["income"]})
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertIn(b"<html", body.lower())
        assets = AssetReferences()
        assets.feed(body.decode("utf-8"))
        self.assertEqual({kind for kind, _ in assets.references}, {"js", "css"})
        for kind, path in assets.references:
            with self.subTest(asset=path):
                self.assertTrue(path.startswith("/") and not path.startswith("//"),
                                "Application assets must work locally without external services")
                status, headers, content = self.request("GET", path)
                self.assertEqual(status, 200)
                mime = headers.get("Content-Type", "").split(";", 1)[0]
                self.assertIn(mime, ("text/javascript", "application/javascript")
                              if kind == "js" else ("text/css",))
                self.assertTrue(content)

    def test_crud_monthly_summary_and_global_balance(self):
        expense = self.create()
        self.create(amount_cents=701, description="Cena", date="2030-05-20")
        self.create(type="income", amount_cents=100000, description="Nómina",
                    category="salary", date="2030-05-01")
        self.create(type="income", amount_cents=5000, description="Ingreso anterior",
                    category="salary", date="2030-04-30")
        data = self.json_request("GET", "/api/data?month=2030-05")
        self.assertEqual(len(data["transactions"]), 3)
        self.assertEqual(data["summary"], {
            "income_cents": 100000, "expense_cents": 2000,
            "balance_cents": 98000, "total_balance_cents": 103000,
            "transaction_count": 3,
        })
        self.assertEqual({row["category"]: row["amount_cents"]
                          for row in data["breakdown"]}, {"food": 2000})
        self.assertTrue({"2030-04", "2030-05"}.issubset(data["available_months"]))

        replacement = self.transaction(amount_cents=3000, description="Compra corregida",
                                       date="2030-06-01")
        updated = self.json_request("PUT", "/api/transactions/" + str(expense["id"]),
                                    replacement)["transaction"]
        self.assertEqual(updated["id"], expense["id"])
        for key, value in replacement.items():
            self.assertEqual(updated[key], value)
        may = self.json_request("GET", "/api/data?month=2030-05")
        june = self.json_request("GET", "/api/data?month=2030-06")
        self.assertEqual(may["summary"]["expense_cents"], 701)
        self.assertEqual(june["summary"]["expense_cents"], 3000)
        self.assertEqual(june["summary"]["total_balance_cents"], 101299)

        status, _, body = self.request("DELETE", "/api/transactions/" + str(expense["id"]))
        self.assertEqual(status, 204)
        self.assertEqual(body, b"")
        june = self.json_request("GET", "/api/data?month=2030-06")
        self.assertEqual(june["transactions"], [])
        self.assertEqual(june["summary"]["total_balance_cents"], 104299)

    def test_invalid_transactions_never_change_the_ledger(self):
        invalid_overrides = [
            {"amount_cents": True}, {"amount_cents": 1.5}, {"amount_cents": "100"},
            {"amount_cents": 0}, {"amount_cents": -1},
            {"type": "transfer"}, {"description": "   "}, {"description": "a" * 201},
            {"category": "not-a-category"}, {"category": "salary"},
            {"date": "2030-02-29"}, {"date": "2030-04-31"},
            {"date": "2030-13-01"}, {"date": "2030-5-1"}, {"date": "yesterday"},
        ]
        for overrides in invalid_overrides:
            with self.subTest(overrides=overrides):
                status, _, _ = self.request("POST", "/api/transactions",
                                             self.transaction(**overrides))
                self.assertIn(status, (400, 422))
        for payload in ({}, [], None, {"type": "income"}):
            with self.subTest(payload=payload):
                status, _, _ = self.request("POST", "/api/transactions", payload)
                self.assertIn(status, (400, 411, 415, 422))
        data = self.json_request("GET", "/api/data?month=2030-05")
        self.assertEqual(data["transactions"], [])
        self.assertEqual(data["summary"]["total_balance_cents"], 0)

    def test_invalid_update_preserves_existing_transaction(self):
        transaction = self.create()
        status, _, _ = self.request("PUT", "/api/transactions/" + str(transaction["id"]),
                                    self.transaction(date="2030-02-30"))
        self.assertIn(status, (400, 422))
        data = self.json_request("GET", "/api/data?month=2030-05")
        self.assertEqual(data["transactions"], [transaction])

    def test_missing_transaction_returns_not_found(self):
        for method, payload in (("PUT", self.transaction()), ("DELETE", None)):
            with self.subTest(method=method):
                status, _, _ = self.request(method, "/api/transactions/999999999", payload)
                self.assertEqual(status, 404)

    def test_transactions_and_currency_survive_restart(self):
        transaction = self.create(description="Persistencia café", amount_cents=12345)
        settings = self.json_request("PUT", "/api/settings", {"currency": "USD"})
        self.assertIn("USD", json.dumps(settings))
        self.stop_server()
        self.start_server()
        data = self.json_request("GET", "/api/data?month=2030-05")
        self.assertEqual(data["currency"], "USD")
        self.assertEqual(data["transactions"], [transaction])
        self.assertEqual(data["summary"]["total_balance_cents"], -12345)
        status, _, _ = self.request("PUT", "/api/settings", {"currency": "INVALID"})
        self.assertIn(status, (400, 422))
        self.assertEqual(self.json_request("GET", "/api/data")["currency"], "USD")

    def test_csv_export_preserves_unicode_and_protects_spreadsheets(self):
        self.create(description="=SUM(1;1)", amount_cents=1234)
        self.create(description="Café, pan y té", date="2030-04-20")
        status, headers, raw = self.request("GET", "/api/export.csv?month=2030-05")
        self.assertEqual(status, 200)
        self.assertIn("text/csv", headers.get("Content-Type", ""))
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "Excel-compatible UTF-8 BOM is missing")
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], ["Fecha", "Tipo", "Categoría", "Descripción", "Importe", "Moneda"])
        self.assertIn("'=SUM(1;1)", rows[1])
        self.assertIn("12.34", rows[1])
        self.assertIn("EUR", rows[1])
        self.assertNotIn("Café, pan y té", rows[1])
        for cell in rows[1]:
            self.assertFalse(cell.startswith(("=", "+", "@")))
        status, _, raw = self.request("GET", "/api/export.csv")
        self.assertEqual(status, 200)
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 3)
        self.assertTrue(any("Café, pan y té" in row for row in rows[1:]))

    def test_invalid_month_is_rejected(self):
        for path in ("/api/data?month=2030-13", "/api/data?month=2030-5",
                     "/api/export.csv?month=not-a-month"):
            with self.subTest(path=path):
                status, _, _ = self.request("GET", path)
                self.assertIn(status, (400, 422))

    def test_external_origin_and_host_cannot_modify_data(self):
        status, _, _ = self.request("POST", "/api/transactions", self.transaction(),
                                    {"Origin": "https://untrusted.example"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("POST", "/api/transactions", self.transaction(),
                                    {"Host": "untrusted.example"})
        self.assertIn(status, (400, 403, 421))
        self.assertEqual(self.json_request("GET", "/api/data?month=2030-05")["transactions"], [])

    def test_server_does_not_serve_source_or_files_outside_static_directory(self):
        for path in ("/app.py", "/../app.py", "/%2e%2e/app.py", "/.git/config",
                     "/static/../app.py", "/static/%2e%2e/app.py",
                     "/static/../../.git/config"):
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertIn(status, (400, 403, 404))
                self.assertNotIn(b"sqlite3.connect", body)


if __name__ == "__main__":
    unittest.main()
