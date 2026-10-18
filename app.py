#!/usr/bin/env python3
"""Financiero: aplicación local, sin servicios ni dependencias externas."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import signal
import sqlite3
import sys
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser


ROOT = Path(__file__).resolve().parent
MAX_AMOUNT_CENTS = 99_999_999_999
MAX_BODY_BYTES = 16_384
CURRENCIES = ("EUR", "USD", "MXN", "COP", "ARS", "CLP", "PEN", "GBP")
CATEGORIES = {
    "expense": [
        {"id": "housing", "label": "Vivienda"},
        {"id": "food", "label": "Alimentación"},
        {"id": "transport", "label": "Transporte"},
        {"id": "health", "label": "Salud"},
        {"id": "shopping", "label": "Compras"},
        {"id": "leisure", "label": "Ocio"},
        {"id": "education", "label": "Educación"},
        {"id": "services", "label": "Servicios"},
        {"id": "other", "label": "Otros"},
    ],
    "income": [
        {"id": "salary", "label": "Sueldo"},
        {"id": "freelance", "label": "Trabajo independiente"},
        {"id": "investment", "label": "Inversiones"},
        {"id": "gift", "label": "Regalos"},
        {"id": "other", "label": "Otros"},
    ],
}
CATEGORY_LABELS = {
    kind: {item["id"]: item["label"] for item in items}
    for kind, items in CATEGORIES.items()
}


class APIError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def default_data_dir() -> Path:
    override = os.environ.get("FINANCIERO_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Financiero"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base).expanduser() if base else Path.home() / ".local" / "share") / "financiero"


@contextmanager
def database(path: Path):
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = data_dir / "financiero.sqlite3"
    with database(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL CHECK (type IN ('income', 'expense')),
                amount_cents INTEGER NOT NULL
                    CHECK (typeof(amount_cents) = 'integer' AND amount_cents > 0
                           AND amount_cents <= 99999999999),
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS transactions_date ON transactions(date);
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO settings(key, value) VALUES ('currency', 'EUR');
            """
        )
    return path


def validate_month(value: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        raise APIError(400, "El mes debe tener el formato AAAA-MM.")
    try:
        dt.date(int(value[:4]), int(value[5:]), 1)
    except ValueError:
        raise APIError(400, "El mes indicado no es válido.") from None
    return value


def validate_transaction(payload: dict) -> dict:
    kind = payload.get("type")
    if not isinstance(kind, str) or kind not in CATEGORIES:
        raise APIError(400, "Selecciona un ingreso o un gasto.")
    amount = payload.get("amount_cents")
    if type(amount) is not int or not 1 <= amount <= MAX_AMOUNT_CENTS:
        raise APIError(400, "El importe debe ser un número entero de céntimos entre 1 y 99999999999.")
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        raise APIError(400, "Escribe una descripción para el movimiento.")
    description = description.strip()
    if len(description) > 200:
        raise APIError(400, "La descripción puede tener como máximo 200 caracteres.")
    if "\x00" in description:
        raise APIError(400, "La descripción contiene un carácter no válido.")
    category = payload.get("category")
    if not isinstance(category, str) or category not in CATEGORY_LABELS[kind]:
        raise APIError(400, "La categoría no corresponde al tipo de movimiento.")
    date = payload.get("date")
    if not isinstance(date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
        raise APIError(400, "La fecha debe tener el formato AAAA-MM-DD.")
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        raise APIError(400, "La fecha indicada no es válida.") from None
    return {"type": kind, "amount_cents": amount, "description": description,
            "category": category, "date": date}


def safe_csv_cell(value: str) -> str:
    # Las comillas de CSV no impiden que una hoja de cálculo evalúe fórmulas.
    if value and (value[0] in "=+-@\t\r\n" or value.lstrip().startswith(("=", "+", "-", "@"))):
        return "'" + value
    return value


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int, database_path: Path):
        self.database_path = database_path
        self.static_dir = ROOT / "static"
        super().__init__(("127.0.0.1", port), RequestHandler)


class RequestHandler(BaseHTTPRequestHandler):
    server: LocalServer
    server_version = "Financiero"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        super().end_headers()

    def send_bytes(self, status: int, body: bytes, content_type: str, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_bytes(status, body, "application/json; charset=utf-8")

    def check_local_request(self, mutation: bool):
        hosts = self.headers.get_all("Host", [])
        port = self.server.server_port
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed_hosts.update({"127.0.0.1", "localhost"})
        if len(hosts) != 1 or hosts[0].lower() not in allowed_hosts:
            raise APIError(403, "Solo se permiten solicitudes dirigidas a esta aplicación local.")
        if mutation:
            origins = self.headers.get_all("Origin", [])
            if origins and (len(origins) != 1 or origins[0].lower() != "http://" + hosts[0].lower()):
                raise APIError(403, "El origen de la solicitud no está permitido.")
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise APIError(403, "El origen de la solicitud no está permitido.")

    def read_json(self) -> dict:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise APIError(415, "Envía el contenido como application/json.")
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
            raise APIError(400, "La solicitud debe indicar una longitud válida.")
        try:
            length = int(lengths[0])
        except ValueError:
            raise APIError(400, "La longitud de la solicitud no es válida.") from None
        if length < 0 or length > MAX_BODY_BYTES:
            raise APIError(413, "La solicitud es demasiado grande.")
        body = self.rfile.read(length)
        if len(body) != length:
            raise APIError(400, "El contenido de la solicitud está incompleto.")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise APIError(400, "El contenido JSON no es válido.") from None
        if not isinstance(payload, dict):
            raise APIError(400, "El contenido JSON debe ser un objeto.")
        return payload

    def month_parameter(self, query: str, required_default: bool = True):
        try:
            params = parse_qs(query, keep_blank_values=True, max_num_fields=20)
        except ValueError:
            raise APIError(400, "Los parámetros de la solicitud no son válidos.") from None
        values = params.get("month")
        if values is None:
            return dt.date.today().strftime("%Y-%m") if required_default else None
        if len(values) != 1:
            raise APIError(400, "Indica un único mes.")
        return validate_month(values[0])

    def dispatch(self):
        mutation = self.command in {"POST", "PUT", "DELETE", "PATCH"}
        self.check_local_request(mutation)
        if not self.path.startswith("/"):
            raise APIError(400, "La ruta solicitada no es válida.")
        try:
            url = urlsplit(self.path)
        except ValueError:
            raise APIError(400, "La ruta solicitada no es válida.") from None
        path = unquote(url.path)
        if path == "/api/data" and self.command == "GET":
            self.get_data(self.month_parameter(url.query))
        elif path == "/api/export.csv" and self.command == "GET":
            self.export_csv(self.month_parameter(url.query, required_default=False))
        elif path == "/api/settings" and self.command == "PUT":
            self.update_settings()
        elif path == "/api/transactions" and self.command == "POST":
            self.save_transaction()
        elif re.fullmatch(r"/api/transactions/[0-9]+", path) and self.command in {"PUT", "DELETE"}:
            value = path.rsplit("/", 1)[1]
            # SQLite admite identificadores enteros de 64 bits.
            if len(value) > 19 or int(value) > 9_223_372_036_854_775_807:
                raise APIError(404, "No se encontró el movimiento.")
            transaction_id = int(value)
            if self.command == "DELETE":
                self.delete_transaction(transaction_id)
            else:
                self.save_transaction(transaction_id)
        elif path.startswith("/api/"):
            raise APIError(404, "No se encontró la ruta solicitada.")
        elif self.command in {"GET", "HEAD"}:
            self.serve_static(path)
        else:
            raise APIError(405, "Este método no está permitido.")

    def handle_request(self):
        try:
            self.dispatch()
        except APIError as error:
            self.close_connection = True
            self.send_json(error.status, {"error": error.message})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except sqlite3.Error:
            self.log_error("No se pudo acceder a la base de datos local.")
            self.send_json(500, {"error": "No se pudo acceder a los datos. Vuelve a intentarlo."})
        except OSError:
            self.log_error("No se pudo leer un archivo de la aplicación.")
            self.send_json(500, {"error": "No se pudo leer un archivo de la aplicación."})

    do_GET = handle_request
    do_HEAD = handle_request
    do_POST = handle_request
    do_PUT = handle_request
    do_DELETE = handle_request
    do_PATCH = handle_request
    do_OPTIONS = handle_request

    def get_data(self, month: str):
        with database(self.server.database_path) as connection:
            rows = connection.execute(
                "SELECT id, type, amount_cents, description, category, date FROM transactions "
                "WHERE date >= ? AND date <= ? ORDER BY date DESC, id DESC",
                (month + "-01", month + "-31"),
            ).fetchall()
            total_balance = connection.execute(
                "SELECT COALESCE(SUM(CASE type WHEN 'income' THEN amount_cents "
                "ELSE -amount_cents END), 0) FROM transactions"
            ).fetchone()[0]
            months = connection.execute(
                "SELECT DISTINCT substr(date, 1, 7) AS month FROM transactions"
            ).fetchall()
            currency = connection.execute("SELECT value FROM settings WHERE key='currency'").fetchone()[0]
        transactions = [dict(row) for row in rows]
        income = sum(item["amount_cents"] for item in transactions if item["type"] == "income")
        expense = sum(item["amount_cents"] for item in transactions if item["type"] == "expense")
        totals = {}
        for item in transactions:
            if item["type"] == "expense":
                totals[item["category"]] = totals.get(item["category"], 0) + item["amount_cents"]
        breakdown = [
            {"category": key, "label": CATEGORY_LABELS["expense"][key], "amount_cents": amount}
            for key, amount in sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))
        ]
        available = {row["month"] for row in months} | {month, dt.date.today().strftime("%Y-%m")}
        self.send_json(200, {
            "month": month,
            "currency": currency,
            "categories": CATEGORIES,
            "transactions": transactions,
            "summary": {"income_cents": income, "expense_cents": expense,
                        "balance_cents": income - expense, "total_balance_cents": total_balance,
                        "transaction_count": len(transactions)},
            "breakdown": breakdown,
            "available_months": sorted(available, reverse=True),
        })

    def save_transaction(self, transaction_id=None):
        transaction = validate_transaction(self.read_json())
        fields = tuple(transaction[key] for key in ("type", "amount_cents", "description", "category", "date"))
        with database(self.server.database_path) as connection:
            if transaction_id is None:
                cursor = connection.execute(
                    "INSERT INTO transactions(type, amount_cents, description, category, date) "
                    "VALUES (?, ?, ?, ?, ?)", fields,
                )
                transaction_id = cursor.lastrowid
                status = 201
            else:
                cursor = connection.execute(
                    "UPDATE transactions SET type=?, amount_cents=?, description=?, category=?, date=? "
                    "WHERE id=?", fields + (transaction_id,),
                )
                if cursor.rowcount == 0:
                    raise APIError(404, "No se encontró el movimiento.")
                status = 200
        self.send_json(status, {"transaction": {"id": transaction_id, **transaction}})

    def delete_transaction(self, transaction_id: int):
        with database(self.server.database_path) as connection:
            cursor = connection.execute("DELETE FROM transactions WHERE id=?", (transaction_id,))
            if cursor.rowcount == 0:
                raise APIError(404, "No se encontró el movimiento.")
        self.send_bytes(204, b"", "application/json; charset=utf-8")

    def update_settings(self):
        currency = self.read_json().get("currency")
        if not isinstance(currency, str) or currency not in CURRENCIES:
            raise APIError(400, "Selecciona una moneda admitida: " + ", ".join(CURRENCIES) + ".")
        with database(self.server.database_path) as connection:
            connection.execute("UPDATE settings SET value=? WHERE key='currency'", (currency,))
        self.send_json(200, {"currency": currency})

    def export_csv(self, month):
        with database(self.server.database_path) as connection:
            query = "SELECT type, amount_cents, description, category, date FROM transactions"
            params = ()
            if month is not None:
                query += " WHERE date >= ? AND date <= ?"
                params = (month + "-01", month + "-31")
            query += " ORDER BY date DESC, id DESC"
            rows = connection.execute(query, params).fetchall()
            currency = connection.execute("SELECT value FROM settings WHERE key='currency'").fetchone()[0]
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["Fecha", "Tipo", "Categoría", "Descripción", "Importe", "Moneda"])
        for row in rows:
            amount = row["amount_cents"]
            writer.writerow([
                row["date"], "Ingreso" if row["type"] == "income" else "Gasto",
                CATEGORY_LABELS[row["type"]][row["category"]], safe_csv_cell(row["description"]),
                f"{amount // 100}.{amount % 100:02d}", currency,
            ])
        filename = f"financiero-{month or 'todos'}.csv"
        self.send_bytes(200, output.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", {
            "Content-Disposition": f'attachment; filename="{filename}"',
        })

    def serve_static(self, path: str):
        if "\x00" in path or "\\" in path or any(part in {".", ".."} for part in path.split("/")):
            raise APIError(404, "No se encontró el archivo.")
        if path == "/":
            relative_path = "index.html"
        elif path.startswith("/static/"):
            relative_path = path[len("/static/"):]
        else:
            raise APIError(404, "No se encontró el archivo.")
        root = self.server.static_dir.resolve()
        candidate = (root / relative_path).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise APIError(404, "No se encontró el archivo.")
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self.send_bytes(200, candidate.read_bytes(), content_type)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Financiero: gestiona ingresos y gastos en tu equipo.")
    parser.add_argument("--port", type=int, default=8765, help="Puerto local (por defecto: 8765).")
    parser.add_argument("--data-dir", type=Path, help="Carpeta donde guardar la base de datos.")
    parser.add_argument("--open-browser", action="store_true", help="Abrir la aplicación en el navegador.")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("El puerto debe estar entre 0 y 65535.")
    data_dir = (args.data_dir or default_data_dir()).expanduser().resolve()
    try:
        database_path = initialize_database(data_dir)
        server = LocalServer(args.port, database_path)
    except (OSError, sqlite3.Error) as error:
        print(f"No se pudo iniciar Financiero: {error}", file=sys.stderr)
        print("Comprueba la carpeta de datos y que el puerto esté libre; puedes usar --port 8766.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Financiero listo en {url}", flush=True)
    print(f"Datos guardados en: {database_path}", flush=True)
    print("Pulsa Control+C para cerrar la aplicación.", flush=True)
    if args.open_browser:
        try:
            opened = webbrowser.open(url, new=2)
        except webbrowser.Error:
            opened = False
        if not opened:
            print(f"Abre esta dirección en tu navegador: {url}", flush=True)

    def terminate(_signum, _frame):
        raise KeyboardInterrupt

    previous_signal = signal.signal(signal.SIGTERM, terminate)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nFinanciero cerrado. Tus datos siguen guardados.", flush=True)
    finally:
        server.server_close()
        signal.signal(signal.SIGTERM, previous_signal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
