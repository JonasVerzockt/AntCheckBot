# AntCheckBot

AntCheckBot ist ein Python-basierter Discord-Bot, der die Verfügbarkeit von Ameisenkolonien auf verschiedenen Online-Shops überwacht und Benachrichtigungen sendet. Der Bot verwendet die AntCheck-API, um Daten abzurufen.

[AntCheck API](https://antcheck.info/api) – Teste den Bot gerne auf meinem [TEST Discord](https://discord.gg/cYtz52MXph)!

---

## Projektstruktur

Das Projekt besteht aus zwei Hauptskripten:

- **`bot.py`**: Das Hauptskript für den Discord-Bot.
- **`grabber.py`**: Skript zum Abrufen und Speichern von Shop- und Produktdaten von der AntCheck-API.

---

## Neue und erweiterte Funktionen (ab Version 2.0)

### Mehrsprachigkeit & Einstellungen
- **Mehrsprachigkeit:** Deutsch und Englisch, automatische Auswahl pro User/Server.
- **Serverweite Konfiguration:** Antwortkanal und Sprache via `/startup`.
- **Benutzersprache:** Individuell einstellbar via `/usersetting`.

### Benachrichtigungen & Verwaltung
- **Slash-Command `/notification`:** Benachrichtigung für eine Ameisenart in bestimmten Regionen einrichten (mit Validierung und optionalem „force“-Modus).
- **Sofortige Verfügbarkeitsprüfung** nach Setzen einer Benachrichtigung.
- **Slash-Command `/delete_notifications`:** Löschen von Benachrichtigungen nach ID.
- **Slash-Command `/history`:** Übersicht über eigene Benachrichtigungen, gruppiert nach Status (active, completed, expired).
- **Slash-Command `/testnotification`:** Testet private Nachrichten-Benachrichtigungen.

### Statistiken & System
- **Slash-Command `/stats`:** Zeigt Statistiken zu aktiven, abgeschlossenen, abgelaufenen und gelöschten Benachrichtigungen sowie die Top 5 gesuchten Arten (nur für Admins).
- **Slash-Command `/system`:** Zeigt Uptime, Datenbank-Integrität, Gesamtanzahl der Benachrichtigungen und Status der Shop-Daten-Datei (nur für Admins).

### Automatisierte Aufgaben
- **Tägliche Bereinigung:** Archiviert Benachrichtigungen, die älter als ein Jahr sind.
- **Regelmäßige Verfügbarkeitsprüfung:** Überprüft alle aktiven Benachrichtigungen und sendet Nachrichten bei Verfügbarkeit.
- **Automatisches Update des Bot-Status:** (Uptime, Server- und Useranzahl).

### Weitere Features
- **Logging:** Mit Rotations-Logfiles.
- **Datenbankstruktur:** Für Server- und Benutzereinstellungen, Benachrichtigungen und globale Statistiken.
- **Kanalgebundene Befehle:** (nur im konfigurierten Channel nutzbar).
- **Hilfefunktion `/help`:** Übersicht aller Befehle.

---

## `bot.py` – Übersicht der wichtigsten Slash-Commands

| Befehl                    | Beschreibung                                                                                 | Wer?           |
|---------------------------|---------------------------------------------------------------------------------------------|----------------|
| `/startup`              | Setzt Sprache & Channel für den Server                                                      | Admin          |
| `/usersetting`          | Setzt die Benutzersprache                                                                   | User           |
| `/notification`         | Neue Benachrichtigung für Art & Region(en) einrichten                                       | User           |
| `/delete_notifications`  | Löscht eigene Benachrichtigungen nach ID                                                    | User           |
| `/history`              | Zeigt eigene Benachrichtigungen (Status: aktiv, abgeschlossen, abgelaufen)                  | User           |
| `/testnotification`     | Testet private Nachrichten-Benachrichtigungen                                               | User           |
| `/stats`                | Zeigt Statistiken und Top 5 Arten                                                           | Admin          |
| `/system`               | Zeigt Systemstatus, Uptime, DB-Integrität, Shopdaten-Status                                 | Admin          |
| `/help`                 | Zeigt alle verfügbaren Befehle                                                              | User           |

---

## `grabber.py`

Dieses Skript ist für das Abrufen von Daten von der AntCheck-API und das Speichern in JSON-Dateien zuständig.

**Funktionen:**
- Ruft Shop- und Produktdaten von der AntCheck-API ab.
- Speichert die abgerufenen Daten in JSON-Dateien für die spätere Nutzung durch den Bot.

---

## Konfiguration

1. Stelle sicher, dass folgende Werte korrekt konfiguriert sind:
   - `TOKEN`: Discord-Bot Token
   - `DATA_DIRECTORY`: Pfad zum Verzeichnis mit Produktdaten
   - `SHOPS_DATA_FILE`: JSON-Datei mit Shop-Daten

---

## Verwendung

1. Führe das `grabber.py`-Skript regelmäßig aus (z.B. alle 6 Stunden via Crontab), um Shop- und Produktdaten von der AntCheck-API abzurufen und zu speichern:
   python grabber.py

2. Starte den Discord-Bot (z.B. in einer Screen-Session, damit er nach einem Reboot automatisch läuft):
   python bot.py

3. Der Bot verbindet sich mit Discord und beginnt, auf Slash-Commands zu reagieren und Benachrichtigungen zu senden.

---

## Lizenz

Dieses Projekt ist unter der [Creative Commons Attribution-NonCommercial 4.0 International License](https://creativecommons.org/licenses/by-nc/4.0/) lizenziert.

[![CC BY-NC 4.0][cc-by-nc-shield]][cc-by-nc]

[cc-by-nc]: https://creativecommons.org/licenses/by-nc/4.0/
[cc-by-nc-shield]: https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg

---

**Hinweis:**  
Für Details zu allen Befehlen und deren Nutzung verwende `/help` direkt im Discord-Server.  
Die vollständige Liste und Beschreibung aller Funktionen findest du im Quellcode (`bot.py`).

---

## Kontakt

Autor: Jonas Beier  
GitHub-Profil: [JonasVerzockt](https://github.com/JonasVerzockt)
