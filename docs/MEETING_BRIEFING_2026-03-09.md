# Meeting-Briefing KI-PDF-Reader

Datum Meeting: Montag, 9. Maerz 2026  
Vorbereitet am: Sonntag, 8. Maerz 2026

## 1) Zielbild fuer das Meeting

Wir wollen gemeinsam entscheiden:

1. Betriebsmodell: Docker (Linux-VM) vs. nativer Windows-Betrieb.
2. Verarbeitungsstrategie: regelbasiert ohne KI vs. hybrid mit KI-Fallback.
3. Naechste Umsetzungsschritte bis produktivem Pilot.

---

## 2) Aktueller Stand (kurz)

Die bestehende Loesung kann bereits:

1. PDF hochladen, verarbeiten, Ergebnisse speichern und exportieren (JSON/CSV/SQL).
2. Positionen, Summen und Bilder aus mehreren bekannten Lieferanten-Layouts extrahieren.
3. Optional KI/LLM und VLM verwenden, aber auch komplett ohne KI laufen.

Status fuer Demo:

1. API, DB und Ollama laufen stabil im Compose-Stack.
2. 3 reale Beispiel-PDFs sind verarbeitet.
3. Offene Punkte sind v. a. Validierung, Regressionstests und finales ERP-Mapping.

---

## 3) Kernaussage: Brauchen wir zwingend KI?

Kurzantwort: Nein, nicht zwingend.

Fachliche Einordnung:

1. Fuer wiederkehrende, bekannte Dokumentlayouts ist ein regelbasierter Parser meist schneller, guenstiger und besser erklaerbar.
2. KI wird vor allem dann wertvoll, wenn viele unbekannte oder haeufig wechselnde Layouts verarbeitet werden muessen.
3. Beste Praxis: parser-first, KI nur als Fallback bei Unsicherheit.

Konkreter Befund am neuen Angebot (`Angebotsnr AN-2025-113 - SR Schauraum GmbH (2).pdf`):

1. Aktueller Parser erkennt Template noch als `generic`, deshalb derzeit keine Positionen im Ergebnis.
2. Die Positions- und Summenzeilen sind aber klar strukturiert und mit einfachen Regeln gut extrahierbar.
3. Das spricht fuer: zuerst regelbasiert erweitern, KI optional spaeter.

---

## 4) Betriebsoptionen (Windows-Realitaet)

### Option A: Windows Server + Linux-VM (Hyper-V) + Docker Compose (Empfehlung)

Beschreibung:

1. Windows Server bleibt Host.
2. In einer Linux-VM laeuft der bestehende Stack nahezu unveraendert.

Vorteile:

1. Schnellster Weg mit geringstem Umbaurisiko.
2. Technisch nah am aktuellen Projektstand.
3. Gute Isolation und reproduzierbare Deployments.

Nachteile:

1. Zusatzebene durch VM.
2. IT braucht Linux-Basisbetrieb in der VM.

Eignung:

1. Sehr gut fuer Pilot und spaeteren stabilen Betrieb.

### Option B: Nativer Windows-Service (ohne Docker)

Beschreibung:

1. API als Python-Windows-Service.
2. PostgreSQL lokal oder separat.
3. KI-Komponente optional spaeter.

Vorteile:

1. Passt gut zu reinem Windows-Operationsmodell.
2. Keine Containerplattform notwendig.

Nachteile:

1. Hoeherer Setup-Aufwand fuer reproduzierbare Deployments.
2. Mehr Handarbeit bei Updates/Abhaengigkeiten.
3. Hoheres Risiko fuer Umgebungsdrift.

Eignung:

1. Moeglich, aber initial meist langsamer als Option A.

### Option C: Desktop-App/EXE fuer Windows

Beschreibung:

1. Anwendung als lokales Programm.

Vorteile:

1. Einfaches Benutzerbild fuer Einzelplatz.

Nachteile:

1. Schlecht fuer Mehrbenutzer/Serverbetrieb.
2. Wartung, Logging, Updates und Integrationen werden schwieriger.

Eignung:

1. Nicht empfehlenswert als zentrales Unternehmenssystem.

---

## 5) KI-Strategieoptionen

### Variante 1: Ohne KI (regelbasiert)

Geeignet wenn:

1. Dokumenttypen ueberschaubar sind.
2. Nachvollziehbarkeit und Stabilitaet priorisiert werden.

Vorteile:

1. Niedrige Laufkosten.
2. Kein GPU-Zwang.
3. Sehr gut auditierbar.

Risiko:

1. Mehr Regelpflege bei neuen Layouts.

### Variante 2: Hybrid (parser-first, KI-Fallback) - Empfohlen

Geeignet wenn:

1. 80-90% bekannte Dokumente vorliegen.
2. Restliche Ausnahmen automatisiert abgefangen werden sollen.

Vorteile:

1. Sehr gutes Kosten/Nutzen-Verhaeltnis.
2. KI-Aufrufe nur bei Bedarf.
3. Schont Ressourcen und erhoeht Robustheit.

Risiko:

1. Zusatzaenderungen fuer Fallback-Trigger und Monitoring.

### Variante 3: KI-first

Geeignet wenn:

1. Hohe Dokumentvielfalt und wenig Musterstabilitaet vorliegt.

Vorteile:

1. Schnellere Abdeckung unbekannter Layouts.

Nachteile:

1. Hoehere Infrastruktur- und Betriebskosten.
2. Mehr Varianz im Ergebnis.
3. Schwierigere Erklaerbarkeit.

---

## 6) Konkrete Empfehlung (vorschlagsfaehig)

Empfohlene Entscheidung:

1. Betrieb: Option A (Windows Server + Linux-VM + Docker Compose).
2. Verarbeitung: Variante 2 (Hybrid), aber Start mit `parser_only` als Standard.
3. KI nur freischalten fuer Faelle mit niedriger Confidence oder fehlenden Pflichtfeldern.

Warum diese Kombination:

1. Schnell produktionsnah.
2. Geringstes Projektrisiko.
3. Gute Story fuer Management: pragmatisch, kostenbewusst, skalierbar.

---

## 7) Umsetzungsplan in 3 Stufen

### Stufe 1 (2-3 Wochen): Regelbasiert produktionsfaehig machen

1. Neues Template fuer das SR-Schauraum-Angebot implementieren.
2. Pflichtfelder und Summenvalidierung ins Ergebnis einbauen.
3. Regressionstests fuer bestehende und neue Muster.

### Stufe 2 (1-2 Wochen): Betriebsreife

1. Backup-Konzept (DB + Uploads + Exporte + Logs).
2. Monitoring/Alerting (Health, Disk, Queue, Fehler).
3. Rechte-, Update- und Rollback-Prozess.

### Stufe 3 (optional, 1-2 Wochen): KI-Fallback

1. Triggerregeln fuer Fallback (z. B. fehlende Positionen/Totals).
2. KI-Lauf nur fuer betroffene Dokumente.
3. Vergleich Parser vs. KI protokollieren.

---

## 8) Entscheidungsfragen fuer morgen

1. Soll fuer den Pilot zunaechst `ohne KI` gestartet werden?
2. Ist Linux-VM auf Windows Server fuer den Betrieb akzeptiert?
3. Welche ERP-Pflichtfelder sind zwingend fuer Go-Live?
4. Wie sollen Alternativpositionen und 0,00-Positionen behandelt werden?
5. Welche SLA gilt fuer Verarbeitung und Support?

---

## 9) 90-Sekunden-Sprechvorlage

"Wir haben bereits eine lauffaehige On-Prem-Loesung mit Upload, Parsing, Export und UI.  
Die Frage ist nicht 'KI ja oder nein', sondern wo KI wirtschaftlich Sinn macht.  
Fuer unsere aktuellen Dokumentmuster reicht ein regelbasierter Ansatz sehr gut und ist am besten pruefbar.  
Ich empfehle deshalb parser-first als Standard und KI nur als gezielten Fallback.  
Betriebstechnisch ist auf eurem Windows-Server am robustesten: Linux-VM mit unserem bestehenden Stack.  
Damit kommen wir schnell in einen stabilen Pilot und halten die Option fuer KI offen, ohne uns frueh festzulegen."  

---

## 10) Backup-Slide (falls Detailfragen kommen)

Technische Eckpunkte:

1. Pipeline: Upload -> Text/Bild-Extraktion -> Template-Parser -> Validierung -> Export.
2. Exporte: JSON, CSV, SQL fuer ERP-Import.
3. Betriebsdaten lokal: Uploads, Logs, Exporte, DB.
4. Datenschutz: On-Prem ohne Cloud-Zwang.

