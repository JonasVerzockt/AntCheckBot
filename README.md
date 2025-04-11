# AntCheckBot

AntCheckBot ist ein Python-basierter Discord-Bot, der die Verfügbarkeit von Ameisenkolonien auf verschiedenen Online-Shops überwacht und Benachrichtigungen sendet. Der Bot verwendet die AntCheck-API, um Daten abzurufen.

[AntCheck API](https://antcheck.info/api) - Den Bot testen gerne auf  meinen [TEST Discord](https://discord.gg/cYtz52MXph)!

---

## Projektstruktur

Das Projekt besteht aus zwei Hauptskripten:

- **`bot.py`**: Das Hauptskript für den Discord-Bot.
- **`grabber.py`**: Skript zum Abrufen und Speichern von Shop- und Produktdaten von der AntCheck-API.

---

### `bot.py`

Dieses Skript enthält die Logik für den Discord-Bot.

#### Hauptfunktionen:
- **Discord-Integration**: Verbindet sich mit Discord und verwaltet Befehle und Ereignisse.
- **Benachrichtigungsverwaltung**: Ermöglicht Benutzern das Abonnieren von Benachrichtigungen für bestimmte Ameisenarten und Regionen.
- **Datenbankintegration**: Verwendet eine SQLite-Datenbank, um Benutzerbenachrichtigungen zu speichern.
- **Regelmäßige Überprüfung**: Plant regelmäßige Aufgaben, um die Verfügbarkeit von Produkten zu überprüfen und Benachrichtigungen zu senden.
- **Slash-Commands**: Implementiert Slash-Commands für die Interaktion mit dem Bot.

#### Neue Funktionen:
1. **Slash Commands**:
   - `/notification`: Richte eine Benachrichtigung für eine Ameisenart in spezifischen Regionen ein.
   - `/stats`: Zeigt Statistiken zu aktiven und abgeschlossenen Benachrichtigungen sowie den Top 5 gesuchten Arten (nur Administratoren).
   - `/history`: Zeigt die Historie der Benachrichtigungen des Nutzers.
   - `/testnotification`: Teste private Nachrichten-Benachrichtigungen.

2. **Automatisierte Aufgaben**:
   - Tägliche Bereinigung (`clean_old_notifications`): Archiviert Benachrichtigungen, die älter als ein Jahr sind.
   - Verfügbarkeitsprüfung (`check_availability`): Überprüft alle aktiven Benachrichtigungen und sendet Nachrichten bei Verfügbarkeit.

---

### `grabber.py`

Dieses Skript ist für das Abrufen von Daten von der AntCheck-API und das Speichern in JSON-Dateien zuständig.

#### Hauptfunktionen:
- API-Daten abrufen: Ruft Shop- und Produktdaten von der AntCheck-API ab.
- JSON-Daten speichern: Speichert die abgerufenen Daten in JSON-Dateien.

---

## Installation

1. Klone das Repository:
git clone https://github.com/JonasVerzockt/AntCheckBot.git

2. Installiere die erforderlichen Bibliotheken:
requests
json
os
time
discord
sqlite3
logging
asyncio

---

## Konfiguration

1. Stelle sicher, dass folgende Werte korrekt konfiguriert sind:
- `TOKEN`: Discord-Bot Token
- `DATA_DIRECTORY`: Pfad zum Verzeichnis mit Produktdaten
- `SHOPS_DATA_FILE`: JSON-Datei mit Shop-Daten

---

## Verwendung

1. Führe das `grabber.py`-Skript aus (z.B. alle 6 Stunden über Crontab), um Shop- und Produktdaten von der AntCheck-API abzurufen und zu speichern:
python grabber.py

2. Starte den Discord-Bot (am besten in einer Screen-Session inklusive Crontab (nach reboot wieder der Bot läuft)):
python bot.py

3. Der Bot verbindet sich mit Discord und beginnt, auf Befehle zu reagieren und Benachrichtigungen zu senden.

---

## Lizenz

Dieses Projekt ist unter der Apache License 2.0 lizenziert.

---

## Kontakt

Autor: Jonas Beier  
GitHub-Profil: [JonasVerzockt](https://github.com/JonasVerzockt)
