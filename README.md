# Financiero

Aplicación de finanzas personales para usar en tu Mac, desde el navegador y con los datos guardados en tu equipo. Permite registrar, editar y eliminar ingresos y gastos, clasificarlos por categorías, consultar el resumen mensual y el desglose de gastos, buscar movimientos y exportarlos a CSV. Empieza sin movimientos de ejemplo y con euros como moneda inicial.

## Abrir en macOS

1. Instala **Python 3.10 o posterior** desde [python.org](https://www.python.org/downloads/macos/) si aún no lo tienes. No necesitas instalar paquetes adicionales.
2. Conserva juntos todos los archivos de esta carpeta.
3. Haz doble clic en **Abrir Financiero.command**. Se abrirá Terminal, iniciará la aplicación y abrirá tu navegador en <http://127.0.0.1:8765>.

Mantén esa ventana de Terminal abierta mientras uses la aplicación. Para detenerla, pulsa **Control + C** en esa ventana. Cerrar la pestaña del navegador no detiene el servidor.

Si Finder no permite ejecutar el archivo, abre Terminal, escribe `cd `, arrastra la carpeta del proyecto a la ventana y pulsa Intro. Ejecuta:

```sh
chmod +x "Abrir Financiero.command"
./"Abrir Financiero.command"
```

También puedes iniciarla directamente desde la carpeta del proyecto:

```sh
python3 app.py --open-browser
```

Si el puerto está ocupado, elige otro:

```sh
python3 app.py --open-browser --port 8766
```

En ese caso, la dirección será <http://127.0.0.1:8766>. El lanzador también admite opciones: `./"Abrir Financiero.command" --port 8766`.

## Uso

- Añade un ingreso o gasto con fecha, importe, categoría y descripción. Puedes editarlo o eliminarlo después.
- Selecciona un mes para consultar ingresos, gastos, saldo y gastos por categoría. Usa la búsqueda y los filtros para localizar movimientos.
- Exporta los movimientos del mes o todo el historial a CSV para abrirlos en una hoja de cálculo.
- Elige la moneda de presentación entre EUR, USD, MXN, COP, ARS, CLP, PEN y GBP. **Cambiar la moneda solo cambia su presentación; no convierte importes ni calcula tipos de cambio.** Usa una misma moneda para tus registros.

## Datos y copias de seguridad

En macOS, los datos se guardan en el archivo SQLite `financiero.sqlite3` dentro de:

```text
~/Library/Application Support/Financiero/
```

Para abrir esa carpeta en Finder, pulsa **Comando + Mayúsculas + G** y pega la ruta anterior. Para hacer una copia de seguridad, detén primero la aplicación con Control + C y copia la carpeta completa a un lugar seguro. Para restaurarla, con la aplicación detenida, conserva una copia de los datos actuales antes de reemplazarlos por tu copia de seguridad. El CSV sirve para consultar tus movimientos; la copia de la carpeta conserva la base de datos y la configuración.

Al actualizar el programa, sustituye los archivos del proyecto y conserva la carpeta de datos. **No borres la carpeta de datos para actualizar.**

Puedes elegir otra carpeta al iniciar:

```sh
python3 app.py --open-browser --data-dir "$HOME/Documents/Mis finanzas"
```

También se admite la variable `FINANCIERO_DATA_DIR`; `--data-dir` tiene prioridad. Cambiar de carpeta abre una base de datos independiente y no traslada los datos anteriores. En otros sistemas, la ubicación predeterminada es `$XDG_DATA_HOME/financiero`, si está definida, o `~/.local/share/financiero`.

## Privacidad y requisitos

El servidor escucha solo en `127.0.0.1`, accesible desde tu propio equipo. No requiere cuentas, servicios externos ni conexión a Internet para funcionar. No incluye sincronización entre dispositivos. La base de datos y los CSV contienen información financiera sin cifrado propio: guárdalos en tu cuenta de usuario y protege sus copias.

Requiere Python 3.10 o posterior y un navegador actual. Usa únicamente la biblioteca estándar de Python y SQLite; no necesitas `pip`, Node.js ni servicios de base de datos adicionales.

## Comprobación para desarrollo

Desde la carpeta del proyecto:

```sh
python3 -m unittest discover -s tests -v
```
