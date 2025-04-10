# AntCheckBot

AntCheckBot ist ein Python-basierter Discord-Bot, der die Verfügbarkeit von Ameisenkolonien auf verschiedenen Online-Shops überwacht und Benachrichtigungen sendet. Der Bot verwendet die AntCheck-API, um Daten abzurufen.

https://antcheck.info/api

## Projektstruktur

Das Projekt besteht aus zwei Hauptskripten:

*   `bot.py`: Das Hauptskript für den Discord-Bot.
*   `grabber.py`: Skript zum Abrufen und Speichern von Shop- und Produktdaten von der AntCheck-API.

### `bot.py`

Dieses Skript enthält die Logik für den Discord-Bot.

#### Hauptfunktionen:

*   **Discord-Integration**: Verbindet sich mit Discord und verwaltet Befehle und Ereignisse.
*   **Benachrichtigungsverwaltung**: Ermöglicht Benutzern das Abonnieren und Abbestellen von Benachrichtigungen für bestimmte Ameisenarten und Regionen.
*   **Datenbankintegration**: Verwendet eine SQLite-Datenbank, um Benutzerbenachrichtigungen zu speichern.
*   **Regelmäßige Überprüfung**: Plant regelmäßige Aufgaben, um die Verfügbarkeit von Produkten zu überprüfen und Benachrichtigungen zu senden.
*   **Slash-Commands**: Implementiert Slash-Commands für die Interaktion mit dem Bot.

### `grabber.py`

Dieses Skript ist für das Abrufen von Daten von der AntCheck-API und das Speichern in JSON-Dateien zuständig.

#### Hauptfunktionen:

*   **API-Daten abrufen**: Ruft Shop- und Produktdaten von der AntCheck-API ab.
*   **JSON-Daten speichern**: Speichert die abgerufenen Daten in JSON-Dateien.

## Funktionen

*   **Automatische Überwachung**: Der Bot überprüft regelmäßig die Verfügbarkeit von Ameisenkolonien.
*   **Discord-Benachrichtigungen**: Sendet Benachrichtigungen an Benutzer, wenn sich der Status einer Kolonie ändert zu verfügbar.
*   **Benutzerverwaltung**: Ermöglicht Benutzern das Abonnieren von Benachrichtigungen.
*   **Datenbankgestützte Konfiguration**: Speichert Benutzerbenachrichtigungen in einer SQLite-Datenbank.
*   **Shop-Datenverwaltung**: Ruft und speichert Shop- und Produktdaten von der AntCheck-API.
*   **API-basierte Daten**: Verwendet die AntCheck-API für aktuelle Informationen.

## Voraussetzungen

### Software:

*   Python 3.6 oder höher

### Python-Bibliotheken:

Die erforderlichen Bibliotheken sind:

*   `discord.py`: Für die Kommunikation mit Discord.
*   `requests`: Für HTTP-Anfragen an die AntCheck-API.

### Weitere Anforderungen:

*   Ein Discord-Bot-Token
*   Ein API-Schlüssel für die AntCheck-API

## Installation

1.  Clone das Repository:

    ```
    git clone https://github.com/JonasVerzockt/AntCheckBot.git
    cd AntCheckBot
    ```

2.  Installiere die erforderlichen Bibliotheken

## Konfiguration

1.  Konfiguriere in beiden Skripten jeweils dem KEY/TOKEN und PFAD

## Verwendung

1.  Führe das `grabber.py`-Skript aus (Am besten im Crontab festlegen, z.b. alle 6h), um Shop- und Produktdaten von der AntCheck-API abzurufen und zu speichern:

    ```
    python grabber.py
    ```

2.  Starte den Discord-Bot (Am besten im Crontab festlegen das beim restart das Skript in einer Screen-Session gestartet wird.):

    ```
    python bot.py
    ```

3.  Der Bot verbindet sich mit Discord und beginnt, auf Befehle zu reagieren und Benachrichtigungen zu senden.

## Lizenz

Dieses Projekt ist unter der Apache License 2.0 lizenziert.

## Kontakt

Autor: Jonas Beier

GitHub-Profil: [JonasVerzockt](https://github.com/JonasVerzockt)
