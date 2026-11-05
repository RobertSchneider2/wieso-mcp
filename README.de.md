# wieso-mcp

> *Wieso selber tippen?*

**[English version → README.md](README.md)**

wieso-mcp ist ein inoffizieller [MCP](https://modelcontextprotocol.io)-Server. Mit ihm kann ein
KI-Agent wie Claude Code in **WISO Steuer** unter Windows arbeiten. Er liest, was schon in der
Erklärung steht. Er macht aus geprüften Bankbuchungen Einträge und tippt sie in eine
**Arbeitskopie**. Danach zeigt er genau, was sich geändert hat. **Er gibt nie etwas ab.** Das
*Abgeben* über ELSTER machst immer du selbst.

Entwickelt und getestet mit **WISO Steuer 2026** (Programmversion 33.03, Steuerjahr 2025). Die
neueste installierte WISO-Version wird automatisch verwendet. Mit `WISO_PROGRAM_YEAR` legst du eine
Version fest.

> **Keine Verbindung zur Buhl Data Service GmbH.** „WISO“ und „WISO Steuer“ sind Marken ihrer
> Inhaber. Sie stehen hier nur, um zu sagen, mit welcher Software das Tool zusammenarbeitet. Das ist
> keine Steuerberatung. Du bist für jeden Wert in deiner Erklärung verantwortlich: Prüfe alles vor
> der Abgabe.

## Was es kann

| Bereich | Tools |
|------|-------|
| Status & Fälle | `wiso_status`, `list_cases`, `prepare_working_copy` |
| ELSTER-Feldkatalog | `search_fields`, `describe_field` |
| Erklärung lesen | `read_return`, `diff_returns` (aus dem ELSTER-XML, das WISO beim *Prüfen* schreibt) |
| Bank-Export (CSV) | `summarize_bank_export`, `enter_proposal`, `verify_entries` |
| Oberfläche (nur Arbeitskopie) | `open_case`, `goto_section`, `nav_cards`, `open_card`, `open_row`, `list_fields`, `read_field`, `set_field`, `table_rows`, `add_table_rows`, `ok`, `cancel`, `save_case`, `ui_snapshot`, `screenshot` |

Typischer Ablauf: `list_cases` → `prepare_working_copy` → `open_case(Kopie)` → `summarize_bank_export` →
`enter_proposal` (erst Probelauf, bestätigen, dann `dry_run=false`) → `save_case` → du startest
*Prüfen* in WISO → `verify_entries`.

## Sicherheit

- **Nie abgeben.** Es gibt kein Tool zum Senden oder Abgeben. Jedes Bedienelement, dessen Name
  abgeben/versenden/senden/übermitteln/authentifizieren/signieren/zertifikat enthält, ist gesperrt,
  ohne Ausnahme.
- **Keine Geheimnisse.** In Passwort-, PIN- und Zertifikatsfelder wird nie geschrieben. Dein
  ELSTER-Login bleibt bei dir.
- **Nur Arbeitskopien.** Eingaben gehen nur in Fälle im Arbeitsordner (`WIESO_MCP_WORKDIR`, Standard
  `%LOCALAPPDATA%\wieso-mcp\work`). Das Original wird nur mit `WIESO_MCP_ALLOW_ORIGINAL=1` angefasst.
  Vor dem ersten Schreiben wird eine Sicherung angelegt.
- **Daten nur lesen.** WISOs Datenbanken werden nur gelesen. Falldateien (`.steuer20xx`) werden nie
  direkt gelesen. Die Erklärung kommt aus dem ELSTER-XML, das WISO selbst schreibt.
- **Läuft im Hintergrund.** Es nutzt nur UI Automation und Nachrichten an WISOs eigenes Fenster.
  Keine globalen Tastendrücke, keine Mausbewegungen. Du kannst nebenher weiterarbeiten.
- **Protokoll.** Jede Eingabe wird in `audit.jsonl` festgehalten (`WIESO_MCP_AUDIT_DIR`).
- **Richtige Datei, nicht nur richtiger Name.** Bevor ein offenes WISO-Fenster weiterverwendet wird, wird
  der volle Pfad des offenen Falls mit dem gewünschten verglichen (aus WISOs Startbefehl, sonst aus der
  Liste der zuletzt geöffneten Dateien). Ein gleichnamiger Fall aus einem anderen Ordner wird abgelehnt.

## Was (noch) nicht geht

Das Tool ist für die Erklärung eines Haushalts entstanden und kein fertiges Produkt. Bevor du dich
darauf verlässt, solltest du wissen, was es noch nicht kann:

- **Dropdowns lassen sich nicht setzen.** WISOs Auswahllisten (Qt-Comboboxen) und Auswahlzellen in
  Tabellen, etwa *Art der Dienstleistung*, *Gezahlt von* oder die Personenauswahl, reagieren im
  Hintergrund weder auf UI Automation noch auf Fensternachrichten. Der Agent meldet sie als
  **Handgriff für dich**: welche Seite, welches Feld, welcher Wert. Diese Felder klickst du selbst.
- **Nur ein komplettes Eingabe-Rezept.** In `mapping.yaml` ist bisher nur *Werbungskosten →
  Arbeitsmittel* fertig und geprüft. Andere Bereiche gehen mit den einfachen UI-Tools (`open_card`,
  `set_field`, `add_table_rows`, …). Funktionierende Wege können danach ins Mapping aufgenommen
  werden.
- **Die Datumsspalte braucht den Vordergrund.** Ein Datum in WISOs Datumsspalte
  (`date_column=True`) klappt nur, wenn WISO das aktive Fenster ist. Standardmäßig steht das
  Buchungsdatum stattdessen vorn in der Beschreibung.
- **Den Navigationsbaum erreicht man nur über Umwege.** Qt ignoriert dort UIA `Invoke`/`Expand`.
  Navigiert wird mit Mausnachrichten an die Koordinaten der Einträge, und das hängt vom Layout ab.
- **Suchfeld und Menüband werden nicht genutzt.** Deren Popups zeigen keine Einträge für UI
  Automation.
- **Rückfragen** wie „Angaben jetzt prüfen?“ werden erkannt, kommen aber noch nicht als
  strukturierte Frage zurück.
- **Prüfen machst du selbst.** Die ELSTER-Prüfung und -Vorschau bleiben ein Schritt für dich.
  wieso-mcp liest danach nur das XML.
- **Nur eine WISO-Version getestet.** Jede neue WISO-Version kann Dialognamen oder das Layout ändern.
  Nach jedem Update die Praxistests (`pytest -m wiso`) laufen lassen, siehe
  [`docs/jahresablauf.md`](docs/jahresablauf.md).
- **Nur Windows, nur deutsche Oberfläche.** Es braucht WISO Steuer als Desktop-Programm, nicht die
  Web-Version.
- **Fester Bank-Export.** `summarize_bank_export` erwartet ein bestimmtes, geprüftes CSV (siehe
  unten). Wie du deine Bankdaten in diese Form bringst, ist deine Sache.

## Format des Bank-Exports

Ein CSV mit Semikolon als Trennzeichen in UTF-8. Es braucht mindestens diese Spalten: `ID`, `Datum`,
`Empfänger`, `Verwendungszweck`, `Betrag`, `Kategorie`, `Label`, `Für Abschluss bestätigt`,
`Im Jahr <Steuerjahr>`. Verwendet werden nur Zeilen mit `Im Jahr <Jahr> = 1` und
`Für Abschluss bestätigt = 1`. Exporte für ein anderes Steuerjahr als den geöffneten Fall werden
abgelehnt. `Kategorie` + `Label` werden in `src/wieso_mcp/mapping.yaml` den WISO-Zielen zugeordnet.
Beispiel: [`tests/fixtures/tax_2025_final_sample.csv`](tests/fixtures/tax_2025_final_sample.csv).

## Für KI-Agenten

Arbeitest du mit einem Agenten an diesem Repo oder nutzt den Server aus einem Agenten heraus? Dann lies
[AGENTS.md](AGENTS.md) (auf Englisch). Dort stehen die festen Sicherheitsregeln, die Befehle, die
Architektur, wie man ein neues Eingabe-Rezept anlegt und der empfohlene Ablauf der Tools.

## Installation

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
claude mcp add --scope user wieso-mcp -- C:/pfad/zu/wieso-mcp/.venv/Scripts/python.exe -m wieso_mcp
```

## Tests

```powershell
.venv\Scripts\pytest                 # Unit-Tests gegen ein nachgebautes WISO-Fenster
.venv\Scripts\pytest -m wiso         # Praxistests gegen das installierte WISO, siehe docs/real-life-test.md
```

Die Praxistests brauchen eine eigene Testkopie eines Falls in `fixtures/private/`. Das Original
fassen sie nie an.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
