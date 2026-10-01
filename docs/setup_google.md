# Configuración de Google Drive y Sheets (OAuth de usuario)

Guía paso a paso con una cuenta Gmail gratuita. El agente usa **OAuth de usuario** (cliente de escritorio) y no una cuenta de servicio: según la documentación de Google, las cuentas de servicio no tienen cuota de almacenamiento y no pueden ser dueñas de archivos ([Drive: unidades compartidas](https://developers.google.com/workspace/drive/api/guides/about-shareddrives)). Ver la adenda A11 en `docs/dev_prompts.md`.

## Privilegio mínimo

Se solicita un único scope, suficiente para las Etapas 4 y 5:

| Scope | Qué permite | Fuente |
|---|---|---|
| `https://www.googleapis.com/auth/drive.file` | Solo los archivos que la aplicación crea o abre; clasificado como no sensible y recomendado. | [Alcances de Drive](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) |

La API de Sheets lista `drive.file` entre sus scopes ([alcances de Sheets](https://developers.google.com/workspace/sheets/api/scopes)) y `spreadsheets.create` lo acepta ([referencia](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/create)).

**Consecuencia:** con `drive.file` la aplicación **no ve** carpetas ni planillas que hayas creado a mano. Por eso `scripts/setup_google_resources.py` crea por API la carpeta y la planilla de prueba. **[SUPUESTO]** Que `drive.file` baste también para agregar filas a esa planilla (Etapa 5) está respaldado por la documentación, pero no se ha probado con la API real. Si fallara, el plan alternativo es agregar el scope `https://www.googleapis.com/auth/spreadsheets` (sensible) y volver a autorizar.

## Pasos

1. **Proyecto.** En [Google Cloud Console](https://console.cloud.google.com/) crea un proyecto nuevo (p. ej. `expense-tracker-prueba`).
2. **APIs.** En *APIs y servicios > Biblioteca* habilita **Google Drive API** y **Google Sheets API**.
3. **Pantalla de consentimiento.** En *APIs y servicios > Pantalla de consentimiento de OAuth*: tipo de usuario **Externo**, estado de publicación **Testing**, y agrega tu propia cuenta Gmail en **Usuarios de prueba**.
4. **Cliente OAuth.** En *Credenciales > Crear credenciales > ID de cliente de OAuth*, tipo **Aplicación de escritorio**. Descarga el JSON.
5. **Guarda el JSON** en `secrets/` (p. ej. `secrets/client_secret.json`). La carpeta `secrets/`, `token.json` y `client_secret*.json` están en `.gitignore`: nunca los subas al repositorio.
6. **Variables en `.env`** (ver `.env.example`):
   ```
   GOOGLE_OAUTH_CLIENT_SECRETS=secrets/client_secret.json
   GOOGLE_OAUTH_TOKEN=secrets/token.json
   ```
7. **Autoriza** (abre el navegador; lo haces tú, una vez):
   ```powershell
   .venv\Scripts\python scripts\google_auth.py
   ```
   Google mostrará un aviso de "app no verificada" porque está en modo Testing: continúa con tu cuenta de prueba. El token se guarda en la ruta de `GOOGLE_OAUTH_TOKEN`.
8. **Crea la carpeta y la planilla de prueba:**
   ```powershell
   .venv\Scripts\python scripts\setup_google_resources.py
   ```
   Imprime `DRIVE_FOLDER_ID=...` y `SHEET_ID=...`; pégalos en `.env`. La planilla se crea con el encabezado `Fecha | Comercio | Monto | Categoría | Recibo_URL` y ninguna fila de datos. Si una de las variables ya está definida, ese recurso no se vuelve a crear; para crearlo de nuevo, vacía la variable.
9. **Verifica la Etapa 4:**
   ```powershell
   .venv\Scripts\python scripts\verify_stage_4.py
   ```
   Sube `data/receipts/receipt_normal.jpg` y confirma con `files.get` que el `file_id` existe. También puedes ejecutar `pytest -m live tests/test_stage4_live.py`.

## Caducidad a los 7 días

Con la pantalla de consentimiento en **Testing** (usuario externo), el token de renovación caduca a los 7 días ([OAuth 2.0 de Google](https://developers.google.com/identity/protocols/oauth2)). Cuando `guardar_recibo` devuelva `success=False` con el mensaje de credenciales vencidas, vuelve a ejecutar `scripts/google_auth.py`. La tool nunca abre el navegador por sí sola.

## Seguridad

- Las credenciales solo se leen de variables de entorno / archivos locales ignorados por git; el trazador enmascara sus rutas.
- `data/` solo contiene recibos sintéticos; Drive y Sheets se usan únicamente con la carpeta y la planilla de prueba. En Sheets solo se agregan filas.
- Para revocar el acceso: tu cuenta de Google > Seguridad > Acceso de terceros y borra `secrets/token.json`.

## Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| `HTTP 403` al subir | API de Drive no habilitada o cuenta no agregada como usuario de prueba. |
| `HTTP 404` al subir | `DRIVE_FOLDER_ID` no corresponde a una carpeta creada por `setup_google_resources.py` (con `drive.file` no se ven carpetas manuales). |
| Mensaje de credenciales vencidas | Token caducado (7 días) o revocado: `scripts/google_auth.py`. |
