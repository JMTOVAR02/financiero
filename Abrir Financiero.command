#!/bin/bash

# Compatible con el Bash incluido en macOS. No descarga ni instala software.
set -u

fail() {
  printf '\n%s\n' "$1" >&2
  if [[ -t 0 ]]; then
    printf '\nPulsa Intro para cerrar esta ventana... '
    read -r _reply || true
  fi
  exit 1
}

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || fail "No se pudo localizar la carpeta de Financiero."
cd -- "$PROJECT_DIR" || fail "No se pudo abrir la carpeta de Financiero."
[[ -f "$PROJECT_DIR/app.py" ]] || fail "Falta app.py. Conserva este lanzador junto con los demás archivos del proyecto."

PYTHON_BIN=""
for candidate in \
  "$(command -v python3 2>/dev/null || true)" \
  "/Library/Frameworks/Python.framework/Versions/Current/bin/python3" \
  "/opt/homebrew/bin/python3" \
  "/usr/local/bin/python3" \
  "/usr/bin/python3"; do
  [[ -n "$candidate" && -x "$candidate" ]] || continue
  if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done

[[ -n "$PYTHON_BIN" ]] || fail "Se necesita Python 3.10 o posterior. Instálalo desde https://www.python.org/downloads/macos/ y vuelve a abrir este archivo."

printf 'Iniciando Financiero. Mantén esta ventana abierta.\n'
printf 'Para detener la aplicación, pulsa Control + C.\n\n'
"$PYTHON_BIN" "$PROJECT_DIR/app.py" --open-browser "$@"
status=$?

if [[ "$status" -ne 0 && "$status" -ne 130 ]]; then
  fail "Financiero se ha detenido con un error (código $status). Revisa el mensaje anterior. Si el puerto está ocupado, prueba: ./\"Abrir Financiero.command\" --port 8766"
fi
exit "$status"
