# Letzte Aenderungen

Stand: 2026-05-28

Diese Datei fasst die groesseren Aenderungen seit Ende April 2026 zusammen. Details stehen weiterhin in `docs/STATUS.md`, `docs/TASKS.md`, `docs/API.md` und `docs/VENDOC_DRAGAN_HANDOVER.md`.

## VenDoc und SRTemp

- MSSQL-Live-Writer fuer `SRTemp` ist im Code umgesetzt und per ENV schaltbar.
- Docker-Image installiert den Microsoft ODBC Driver 18 und `pyodbc`.
- `GET /vendoc/health?check_connection=true` prueft optional die echte SQL-Verbindung.
- Live-Export schreibt Header und Positionen transaktional nach:
  - `dbo.vendoc_import_headers`
  - `dbo.vendoc_import_positions`
- Live-Export bleibt gesperrt, wenn das Dokument nicht verarbeitet oder nicht freigegeben ist.
- UI warnt vor erneutem Import, wenn bereits ein erfolgreicher Live-Export im Export-Journal steht.
- Export-Journal und Import-State zeigen Dry-Run, Live-Export, Fehler und letzten Stand je Dokument.
- Kundenzuordnung in `SRTemp` ist im Startbereich der UI sichtbar.
- `customer_id` wird in den VenDoc-Header geschrieben.
- Kundensuche/-auswahl kommt aus `SRTemp`, wenn MSSQL aktiv ist.
- SQL-Vorschau/Dry-Run kann weiterhin ohne echten Write genutzt werden.

## VenDoc Positionsdaten

- `description_short` wird vor dem Export bereinigt, damit Preise nicht im Kurztext landen.
- `description_long` bleibt als Plaintext erhalten.
- Gewichts- und Umfangsangaben bleiben im Langtext erhalten.
- `image_long_text_rtf` bleibt das kombinierte RTF-Feld mit Text und Bild.
- Zusaetzlich werden optional erzeugt:
  - `text_only_rtf`
  - `image_only_rtf`
- Bilder werden als PNG-Hex in RTF eingebettet.
- Der Export toleriert fehlende optionale RTF-Spalten im Zielsystem.

## Alternativpositionen

- Pro Dokument gibt es `alternative_position_mode`.
- Modus `nested`: Alternativen erscheinen direkt unter der Hauptposition, z.B. `1.1`.
- Modus `append`: Alternativen werden gesammelt am Ende angehaengt.
- Exportpositionen werden fuer VenDoc lueckenlos neu nummeriert.
- Gleiche angehaengte Alternativen koennen zu Sammelpositionen zusammengefasst werden.
- UI zeigt Originalposition und geplante Exportposition.

## Login, Benutzer und Audit

- App-Login ist implementiert und per `APP_AUTH_ENABLED=true` aktivierbar.
- Initialer Benutzer kann per Bootstrap-ENV angelegt werden:
  - `APP_BOOTSTRAP_USERNAME`
  - `APP_BOOTSTRAP_PASSWORD`
  - `APP_BOOTSTRAP_DISPLAY_NAME` optional
- Wenn noch kein Benutzer existiert, kann der erste Benutzer ueber die Setup-Route angelegt werden.
- Weitere Benutzer koennen in der UI im Admin-Bereich angelegt werden.
- UI wurde vereinfacht: fuer die Bedienung reichen Benutzername und Passwort.
- Kopfzeile zeigt den angemeldeten Benutzer und bietet `Abmelden`.
- Rollenmodell ist bewusst noch nicht umgesetzt; alle angemeldeten Benutzer haben aktuell dieselben Rechte.
- Audit-Log protokolliert u.a. Login/Logout, Upload, Verarbeitung, Bildzuordnung, Freigabe, Kundenzuordnung, Dry-Run, Live-Export und Reset.

## UI

- Kompakte Operator-Leiste mit Schauraum-Logo, Dokumentauswahl, Upload und Re-Run.
- Login-Dialog und sichtbarer Logout in der Hauptkopfzeile.
- Admin-Panel fuer Benutzeranlage, JSON/CSV-Vorschau, Reset und Live-Debug.
- Kundenauswahl in `Start`.
- Alternativmodus in `Positionen`.
- Duplicate-Import-Warnung als App-Modal statt Browser-Popup.
- Positionsfilter klarer benannt: `Nur mit Fehlern/Warnungen`.

## Parser, Provider und Validierung

- Aktueller Angebots-Smoke-Korpus: 39 Angebotsfaelle ueber 11 Anbieter.
- Unterstuetzte Anbieter im Korpus:
  - `alu_one`
  - `entholzer`
  - `koch`
  - `muigg`
  - `newo`
  - `rekord_vomp`
  - `rieder`
  - `schachermayer`
  - `schlotterer`
  - `schuchter`
  - `sr_schauraum`
- Alu-One Kandidat `Angebot 2400061DL-1_i.pdf` wurde fachlich auf 30 Positionen festgezogen.
- Koch Detailzeichnungswarnung greift nur noch bei aktiver Bildvalidierung.
- SR-Schauraum Summen werden konsistent mit Euro-Prefix erwartet.
- Canary-Korpus wurde um zwei Schuchter-Faelle erweitert.
- Canary kann sich bei aktivierter Auth automatisch anmelden:
  - ueber `PDR_CANARY_USERNAME` / `PDR_CANARY_PASSWORD`
  - oder ueber `APP_BOOTSTRAP_USERNAME` / `APP_BOOTSTRAP_PASSWORD` aus `.env`

## Verifikation

Zuletzt lokal ausgefuehrt:

```bash
env PYTHONPATH=api .venv/bin/python -m pytest tests -q
```

Ergebnis:

```text
209 passed, 2 warnings
```

Die zwei Warnings sind FastAPI-Deprecation-Hinweise zu `on_event`.

Zusaetzlich geprueft:

```bash
bash -n infra/api-canary.sh
git diff --check
```

Hinweis: Ein echter produktiver SRTemp-Live-Write muss nach Deployment mit VPN/MSSQL-Zugang noch gezielt gegen `external_document_id` und die beiden Zieltabellen geprueft werden.
