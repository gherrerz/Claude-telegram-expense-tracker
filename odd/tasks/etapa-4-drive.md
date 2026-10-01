# Etapa 4 — Tool `guardar_recibo` (Google Drive)

**Objetivo:** subir la imagen del recibo a una carpeta de prueba de Drive y devolver `{success, file_id, file_name, web_view_link}`, con el link tomado de la respuesta de la API.
**Decisión del autor (2026-09-30, adenda A11):** OAuth de usuario (cliente de escritorio y `token.json` local) para Drive y Sheets, en lugar de cuenta de servicio. Motivo: las cuentas de servicio no tienen cuota en Drive (https://developers.google.com/workspace/drive/api/guides/about-shareddrives).
**Ruta:** delegated direct (writer trigger). Rama `feat/etapa-4-drive`.
**TDD:** desactivado; pruebas funcionales offline (servicio falso) y en vivo (`live`).
**Restricciones:**
- El agente de desarrollo no inicia sesión ni autoriza OAuth: el consentimiento en el navegador lo hace el autor.
- `.env.example` lo edita el autor.
- A10 (tope 3,0) se decide en la Etapa 6.

## Tareas
- [x] T1 Dependencias de Google fijadas y configuración OAuth en `app/config.py` (variables nuevas y validación).
- [x] T2 `app/google_auth.py` y `scripts/google_auth.py`: flujo de escritorio, `token.json` y scopes mínimos.
- [x] T3 `scripts/setup_google_resources.py`: crea la carpeta de prueba e imprime su ID.
- [x] T4 `app/tools/drive.py`: `guardar_recibo` con nombre normalizado, link desde la API y error estructurado sin credenciales.
- [x] T5 Pruebas offline, prueba `live` y `scripts/verify_stage_4.py` (sube y confirma el `file_id` con `files.get`).
- [x] T6 `docs/setup_google.md`, Sección 8 del notebook, bitácora y A11 en `docs/dev_prompts.md`.
- [ ] T7 El autor configura OAuth y `.env`; verificación real.

## Evidencia
- Dependencias fijadas: google-api-python-client==2.201.0, google-auth==2.59.1, google-auth-oauthlib==1.5.0, google-auth-httplib2==0.4.3 (`pip install -r requirements.txt` OK en Python 3.12.3).
- Scope: solo `drive.file` (Drive y Sheets; `spreadsheets.create` lo acepta). **[SUPUESTO]** el append de la Etapa 5 con `drive.file` no está probado contra la API real.
- Símbolos confirmados en el código instalado: `InstalledAppFlow.from_client_secrets_file(client_secrets_file, scopes)`, `run_local_server(port=0)`, `Credentials.from_authorized_user_file(filename, scopes)`, `Credentials.refresh/valid/to_json`, `MediaIoBaseUpload(fd, mimetype, resumable)`, `build(..., credentials=, cache_discovery=)`.
- `pytest -q -m "not live"` con variables en blanco: 114 passed, 2 failed. Los 2 fallos son esperados: `.env.example` aún no declara `GOOGLE_OAUTH_CLIENT_SECRETS` / `GOOGLE_OAUTH_TOKEN` (lo edita el autor).
- nbconvert con variables en blanco: ejecuta de principio a fin; la celda de subida imprime "omitido: ...".
- `scripts/verify_stage_4.py` con variables en blanco: salida 2, mensaje claro, sin red.
- No se ejecutó ninguna llamada real a Google ni el flujo OAuth.
