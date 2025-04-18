# AntCheckBot v3.5

AntCheckBot ist ein Discord-Bot zur Benachrichtigung über verfügbare Ameisenarten in Online-Shops. Er bietet umfangreiche Mehrsprachigkeit, flexible Benachrichtigungsoptionen, Shop-Blacklist, Statistiken, Systeminfos und automatisierte Aufgaben. Die aktuelle Version nutzt SQLite und JSON für Datenhaltung und ist modular aufgebaut.

[AntCheck API](https://antcheck.info/api) – Teste den Bot gerne auf meinem [TEST Discord](https://discord.gg/cYtz52MXph)! - [BOT](https://top.gg/de/bot/1359846733059850442) einladen!

---

## Projektstruktur

Das Projekt besteht aus mehreren Hauptkomponenten:

- **`bot.py`**: Das Hauptskript für den Discord-Bot mit allen Slash-Commands, Events und Automatisierungen.
- **`grabber.py`**: Skript zum Abrufen und Speichern von Shop- und Produktdaten von der AntCheck-API.
- **`locales/`**: JSON-Dateien für Mehrsprachigkeit (`de.json`, `en.json`, `eo.json`).

---

## Neue und erweiterte Funktionen (ab Version 3.5)

- **Mehrsprachigkeit:** Deutsch, Englisch, Esperanto (pro Server/Benutzer konfigurierbar)
- **Benachrichtigungen:** Erhalte Infos, sobald eine gewünschte Art in bestimmten Regionen verfügbar ist
- **Shop-Blacklist:** Schließe Shops individuell von Benachrichtigungen aus
- **Shop-Ratings:** Automatischer Import und Anzeige von Shop-Bewertungen
- **Statistiken & Systemstatus:** Umfangreiche Auswertungen für Admins
- **Automatisierung:** Regelmäßige Datenaktualisierung, Datenbankpflege, Statusupdates
- **Kanalbindung:** Befehle können auf einen Server-Channel beschränkt werden (Für das Mappen der Shops)
- **Logging:** Rotierende Logfiles

## Setup

1. **Abhängigkeiten installieren:**
pip install discord.py thefuzz psutil google-auth google-auth-oauthlib google-api-python-client

2. **Konfiguration:**
- `TOKEN` in `bot.py` mit deinem Discord-Bot-Token ersetzen
- `DATA_DIRECTORY`, `SHOPS_DATA_FILE` und `SERVER_IDS` anpassen

3. **Starten:**
python bot.py
python grabber.py (Regelmäßig per Crontab)

## Slash-Commands (Auswahl)

| Befehl                | Beschreibung                                                         | Wer?  |
|-----------------------|-----------------------------------------------------------------------|-------|
| `/startup`            | Sprache & Channel für Server setzen                                   | Admin |
| `/usersetting language` | Eigene Sprache setzen                                              | User  |
| `/usersetting blacklist_add` | Shop zur Blacklist hinzufügen                            | User  |
| `/usersetting blacklist_remove` | Shop von Blacklist entfernen                         | User  |
| `/usersetting blacklist_list` | Eigene Blacklist anzeigen                                | User  |
| `/usersetting shop_list` | Alle Shops (optional nach Land) anzeigen                       | User  |
| `/notification`       | Benachrichtigung für Art & Region einrichten                         | User  |
| `/delete_notifications` | Eigene Benachrichtigungen löschen                                | User  |
| `/history`            | Eigene Benachrichtigungen (Status: aktiv, abgeschlossen, abgelaufen) | User  |
| `/testnotification`   | Test-PN senden                                                       | User  |
| `/stats`              | Statistiken anzeigen                                                 | Admin |
| `/system`             | System- und Performanceinfos anzeigen                                | Admin |
| `/help`               | Übersicht aller Befehle                                              | User  |
| `/reloadshops`        | Shopdaten neu laden                                                  | Admin |
| `/shopmapping ...`    | Shop-Mappings für Google Sheets verwalten                            | Admin |

## Automatisierte Aufgaben

- **Verfügbarkeitsprüfung:** Alle 5 Minuten für aktive Benachrichtigungen
- **Shopdaten-Reload:** Stündlich
- **Shop-Ratings Sync:** Alle 48 Stunden von Google Sheets
- **Alte Benachrichtigungen:** Nach 1 Jahr automatisch als "expired" markiert und User benachrichtigt
- **DB-Optimierung:** Wöchentlich
- **Bot-Status:** Minütlich aktualisiert (Uptime, Server-/Userzahl)

## Datenbankstruktur

- **server_settings:** Channel & Sprache pro Server
- **user_settings:** Sprache pro User
- **shops:** Shopdaten inkl. Bewertung
- **notifications:** Benachrichtigungen (Status: active, completed, expired)
- **user_shop_blacklist:** Blacklist pro User
- **shop_name_mappings:** Zuordnung externer Shopnamen (Google Sheets) zu internen IDs
- **global_stats:** Gesamtstatistiken (z. B. gelöschte Benachrichtigungen)

## Hinweise

- Die Datei `shops_data.json` und Produktdaten müssen regelmäßig aktuell gehalten werden.
- Für Shop-Ratings wird ein Google Sheets Import unterstützt (siehe Funktion `load_shop_data_from_google_sheets`).
- Alle Texte sind mehrsprachig in `locales/` als JSON abgelegt.
- Für weitere Details zu Befehlen und Texten siehe `/help` im Bot.

## Lizenz

Dieses Projekt ist unter der [Creative Commons Attribution-NonCommercial 4.0 International License](https://creativecommons.org/licenses/by-nc/4.0/) lizenziert.

[![CC BY-NC 4.0][cc-by-nc-shield]][cc-by-nc]

[cc-by-nc]: https://creativecommons.org/licenses/by-nc/4.0/
[cc-by-nc-shield]: https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg

**Autor:** Jonas Beier  
**GitHub:** [JonasVerzockt](https://github.com/JonasVerzockt/)
