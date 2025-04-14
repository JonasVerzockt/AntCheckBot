#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File: bot.py
Author: Jonas Beier
Date: 2025-04-11
Version: 1.2
Description:
    Dieses Skript implementiert einen Discord-Bot mit verschiedenen Funktionen, 
    darunter Benachrichtigungen, Statistiken und Systemstatus. Es verwendet SQLite 
    zur Speicherung von Benachrichtigungen und JSON-Dateien für Shop-Daten.

Dependencies:
    - discord.py
    - sqlite3
    - asyncio
    - json
    - logging
    - psutil
    - platform

Setup:
    1. Installiere die benötigten Python-Bibliotheken:
       pip install discord.py
    2. Stelle sicher, dass die Datei `shops_data.json` und der Datenbankpfad korrekt konfiguriert sind.
    3. Setze den Discord-Bot-Token in der Variable `TOKEN`.

License: CC BY-NC 4.0
Contact: https://github.com/JonasVerzockt/
"""
import discord
from discord.ext import commands, tasks
import sqlite3
import json
import os
import logging
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
import asyncio
import psutil
import platform
from datetime import timedelta

# Logging konfigurieren
def setup_logger():
    log_file = os.path.join(os.getcwd(), f"bot_log_{datetime.now().strftime('%Y%m%d')}.log")
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    handler = RotatingFileHandler(log_file, maxBytes=1024*1024, backupCount=5, encoding='utf8')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

setup_logger()

# Bot-Konfiguration
TOKEN = "TOKEN"
DATA_DIRECTORY = "PFAD"
SHOPS_DATA_FILE = "shops_data.json"

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = discord.Bot(intents=intents)

# SQLite-Datenbank mit Status-Spalte
conn = sqlite3.connect("notifications.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    species TEXT,
    regions TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS global_stats (
    key TEXT PRIMARY KEY,
    value INTEGER DEFAULT 0
)
""")
cursor.execute("INSERT OR IGNORE INTO global_stats (key, value) VALUES ('deleted_notifications', 0)")
conn.commit()

# Shop-Daten laden
def load_shop_data():
    shop_data = {}
    try:
        with open(SHOPS_DATA_FILE, "r") as f:
            shops = json.load(f)
            for shop in shops:
                shop_id = shop["id"]
                shop_data[shop_id] = {
                    "country": shop["country"],
                    "name": shop["name"],
                    "url": shop["url"]
                }
        return shop_data
    except FileNotFoundError:
        logging.error(f"{SHOPS_DATA_FILE} nicht gefunden.")
        return {}

SHOP_DATA = load_shop_data()

# Hilfsfunktionen
def species_exists(species):
    for filename in os.listdir(DATA_DIRECTORY):
        if filename.endswith(".json"):
            file_path = os.path.join(DATA_DIRECTORY, filename)
            with open(file_path, "r") as f:
                data = json.load(f)
                for product in data:
                    if "title" in product and product["title"].strip().lower() == species.lower():
                        return True
    return False

def check_availability_for_species(species, regions):
    available_products = []
    for filename in os.listdir(DATA_DIRECTORY):
        if filename.endswith(".json"):
            file_path = os.path.join(DATA_DIRECTORY, filename)
            with open(file_path, "r") as f:
                data = json.load(f)
                for product in data:
                    if ("title" in product
                        and product["title"].strip().lower() == species.lower()
                        and product.get("in_stock", False)):
                        shop_id = product["shop_id"]
                        if shop_id in SHOP_DATA and SHOP_DATA[shop_id]["country"] in regions:
                            available_products.append({
                                "species": product["title"],
                                "shop_name": SHOP_DATA[shop_id]["name"],
                                "min_price": product["min_price"],
                                "max_price": product["max_price"],
                                "currency_iso": product["currency_iso"],
                                "antcheck_url": product["antcheck_url"],
                                "shop_url": SHOP_DATA[shop_id]["url"],
                                "shop_id": shop_id
                            })
    return available_products

def get_file_age(file_path):
    try:
        modification_time = os.path.getmtime(file_path)
        modification_date = datetime.fromtimestamp(modification_time)

        current_date = datetime.now()

        time_difference = current_date - modification_date
        age_hours, remainder = divmod(time_difference.seconds, 3600)
        age_minutes = remainder // 60

        if time_difference.days > 0:
            return f"{time_difference.days} Tage alt", modification_date.strftime('%Y-%m-%d %H:%M:%S')
        elif age_hours > 0:
            return f"{age_hours} Stunden und {age_minutes} Minuten alt", modification_date.strftime('%Y-%m-%d %H:%M:%S')
        else:
            return f"{age_minutes} Minuten alt", modification_date.strftime('%Y-%m-%d %H:%M:%S')
    except FileNotFoundError:
        logging.error(f"Datei '{file_path}' nicht gefunden.")
        return None, None

# Kernfunktionen
async def trigger_availability_check(user_id, species, regions):
    regions_list = regions.split(",")
    available_products = check_availability_for_species(species, regions_list)
    if available_products:
        try:
            user = await bot.fetch_user(int(user_id))
            for product in available_products:
                message = (
                    f"**Ameisenart:** {product['species']} - **Shop:** {product['shop_name']}\n"
                    f"**Preis:** {product['min_price']} - {product['max_price']} {product['currency_iso']}\n"
                    f"[Produkt URL](<{product['antcheck_url']}>) | [Shop-Startseite URL](<{product['shop_url']}>)\n"
                )
                await user.send(message)

            cursor.execute("UPDATE notifications SET status='completed' WHERE user_id=? AND species=? AND regions=?",
                          (user_id, species, regions))
            conn.commit()
        except Exception as e:
            logging.error(f"Fehler bei Verfügbarkeitsprüfung: {e}")

# Befehle
@bot.slash_command(name="delete_notifications", description="Lösche mehrere Benachrichtigungen")
async def delete_notifications(ctx, ids: str):
    try:
        id_list = [int(i.strip()) for i in ids.split(",") if i.strip().isdigit()]
        if not id_list:
            await ctx.respond("❌ Bitte kommagetrennte IDs angeben")
            return

        cursor.execute(
            f"SELECT id FROM notifications WHERE user_id=? AND id IN ({','.join(['?']*len(id_list))})",
            (str(ctx.author.id), *id_list)
        )
        user_ids = [row[0] for row in cursor.fetchall()]
        
        if not user_ids:
            await ctx.respond("❌ Keine berechtigten Benachrichtigungen gefunden")
            return

        # Löschvorgang
        cursor.execute(
            f"DELETE FROM notifications WHERE user_id=? AND id IN ({','.join(['?']*len(user_ids))})",
            (str(ctx.author.id), *user_ids)
        )
        
        # Globalen Zähler aktualisieren
        cursor.execute(
            "UPDATE global_stats SET value = value + ? WHERE key = 'deleted_notifications'",
            (len(user_ids),)
        )
        conn.commit()

        await ctx.respond(f"🗑️ Erfolgreich gelöscht: {', '.join(map(str, user_ids))}")
    except Exception as e:
        logging.error(f"Löschfehler: {e}")
        await ctx.respond("❌ Kritischer Fehler beim Löschen")

@bot.slash_command(name="stats", description="Zeigt Benachrichtigungsstatistiken")
@commands.has_permissions(administrator=True)
async def stats(ctx):
    try:
        cursor.execute("SELECT COUNT(*) FROM notifications WHERE status='active'")
        active = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM notifications WHERE status='completed'")
        completed = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM notifications WHERE status='expired'")
        expired = cursor.fetchone()[0]

        cursor.execute("SELECT species, COUNT(*) FROM notifications GROUP BY species ORDER BY COUNT(*) DESC LIMIT 5")
        top_species = cursor.fetchall()

        cursor.execute("SELECT value FROM global_stats WHERE key = 'deleted_notifications'")
        deleted_total = cursor.fetchone()[0]

        stats_msg = (
            f"**📊 Statistik**\n"
            f"Aktive Benachrichtigungen: {active}\n"
            f"Abgeschlossene Benachrichtigungen: {completed}\n"
            f"Abgelaufene Benachrichtigungen: {expired}\n"
            f"**Global gelöscht:** {deleted_total}\n"
            f"**Top 5 gesuchte Arten:**\n"
        )
        for species, count in top_species:
            stats_msg += f"- {species}: {count} Anfragen\n"

        await ctx.respond(stats_msg)
    except Exception as e:
        logging.error(f"Fehler in stats: {e}")
        await ctx.respond("Fehler beim Abrufen der Statistiken")

@bot.slash_command(name="history", description="Zeigt deine Benachrichtigungshistorie")
async def history(ctx):
    try:
        cursor.execute("SELECT id, species, regions, status, created_at FROM notifications WHERE user_id=? ORDER BY created_at DESC", (str(ctx.author.id),))
        history = cursor.fetchall()

        if not history:
            await ctx.respond("❌ Keine vergangenen Benachrichtigungen gefunden")
            return

        grouped_history = {
            "completed": [],
            "expired": [],
            "active": [],
            "other": []
        }

        for entry in history:
            if entry[3] == "completed":
                grouped_history["completed"].append(entry)
            elif entry[3] == "expired":
                grouped_history["expired"].append(entry)
            elif entry[3] == "active":
                grouped_history["active"].append(entry)
            else:
                grouped_history["other"].append(entry)

        history_msg = "**📜 Deine Historie:**\n"

        for status, entries in grouped_history.items():
            if not entries:
                continue

            if status == "completed":
                status_emoji = "✅ Abgeschlossen:"
            elif status == "expired":
                status_emoji = "⏳ Abgelaufen:"
            elif status == "active":
                status_emoji = "🔄 Aktiv:"
            else:
                status_emoji = "❓ Sonstige:"

            displayed_entries = entries[:10]
            remaining_count = len(entries) - 10

            history_msg += f"\n**{status_emoji}**\n"
            for entry in displayed_entries:
                history_msg += f"- {entry[1]} in {entry[2]} ({entry[4].split()[0]}) - [ID: {entry[0]}]\n"

            if remaining_count > 0:
                history_msg += f"  ...und {remaining_count} weitere\n"

        await ctx.respond(history_msg)
    except Exception as e:
        logging.error(f"Fehler in history: {e}")
        await ctx.respond("Fehler beim Abrufen der Historie")

@bot.slash_command(name="notification", description="Richte eine Benachrichtigung ein")
async def notification(ctx, species: str, regions: str, force: bool = False):
    regions_list = [r.strip() for r in regions.split(",")]
    valid_regions = [r for r in regions_list if any(s["country"] == r for s in SHOP_DATA.values())]
    if not valid_regions:
        available_regions = sorted({s["country"] for s in SHOP_DATA.values()})
        available_regions_str = ", ".join(available_regions)
        await ctx.respond(f"❌ Ungültige Regionen angegeben. Verfügbare Regionen sind: {available_regions_str}. [ISO 3166 ALPHA-2](<https://de.wikipedia.org/wiki/ISO-3166-1-Kodierliste>)")
        return

    species_found = species_exists(species)

    if species_found or force:
        try:
            cursor.execute("INSERT INTO notifications (user_id, species, regions) VALUES (?, ?, ?)",
                          (str(ctx.author.id), species, ",".join(valid_regions)))
            conn.commit()

            if not species_found:
                await ctx.respond(f"⚠️ Art **{species}** wurde nicht gefunden, aber die Benachrichtigung wurde dennoch eingerichtet (Force-Modus aktiviert).")
            else:
                await ctx.respond(f"🔔 Benachrichtigung für **{species}** in {', '.join(valid_regions)} eingerichtet")

            await trigger_availability_check(ctx.author.id, species, ",".join(valid_regions))
        except sqlite3.IntegrityError:
            await ctx.respond("❌ Diese Benachrichtigung existiert bereits exakt so schon.")
    else:
        await ctx.respond("❌ Art nicht gefunden, achte auf die korrekte Schreibweise oder diese Art ist noch nie gelistet worden.")

@bot.slash_command(name="testnotification", description="Teste PN-Benachrichtigungen")
async def testnotification(ctx):
    try:
        await ctx.author.send("📨 Testnachricht erfolgreich!")
        await ctx.respond("✅ Testnachricht gesendet!", ephemeral=True)
    except discord.Forbidden:
        await ctx.respond("❌ Konnte keine PN senden - bitte Privatnachrichten aktivieren")

@bot.slash_command(name="system", description="Zeigt den Status des Bots und des Systems")
@commands.has_permissions(administrator=True)
async def system(ctx):
    try:
        current_time = datetime.now()
        uptime = current_time - bot.start_time

        cursor.execute("SELECT COUNT(*) FROM notifications")
        total_notifications = cursor.fetchone()[0]

        integrity_check = cursor.execute("PRAGMA integrity_check").fetchone()[0]

        file_age, last_modified = get_file_age(SHOPS_DATA_FILE)
        
        if file_age is not None:
            file_status = f"Letzte Änderung: {last_modified} ({file_age})"
        else:
            file_status = "Datei nicht gefunden oder Fehler beim Lesen."

        system_message = (
            f"**🤖 Bot-Status**\n"
            f"Uptime: {str(timedelta(seconds=uptime.total_seconds()))}\n\n"
            f"**🔍 Datenbankstatus:** {integrity_check}\n"
            f"Gesamte Benachrichtigungen in der DB: {total_notifications}\n\n"
            f"**📂 Shop-Daten:**\n{file_status}\n"
        )

        await ctx.respond(system_message)
    except Exception as e:
        logging.error(f"Fehler im /system-Befehl: {e}")
        await ctx.respond("❌ Fehler beim Abrufen des Status")

@bot.slash_command(name="help", description="Zeigt alle Befehle an.")
async def help(ctx):
    try:
        help_message = (
            f"`/notification`\n"
            f"Beschreibung: Erstellt eine Benachrichtigung für eine bestimmte Ameisenart in spezifischen Regionen.\n"
            f"Anforderungen:\n"
            f"- `species`: Name der Ameisenart.\n"
            f"- `regions`: Komma-separierte Liste von Regionen (z. B. de,ch).\n"
            f"Verwendung: /notification species:<Ameisenart> regions:<Regionen>\n\n"
            f"`/delete_notifications`\n"
            f"Beschreibung: Löscht mehrere Benachrichtigungen anhand ihrer IDs (kommagetrennt)\n"
            f"Verwendung: /delete_notifications ids:12,34,56\n\n"
            f"`/history`\n"
            f"Beschreibung: Zeigt die Historie der Benachrichtigungen des Nutzers.\n"
            f"Anforderungen: Keine speziellen Berechtigungen erforderlich.\n"
            f"Verwendung: /history\n\n"
            f"`/testnotification`\n"
            f"Beschreibung: Sendet eine Testnachricht an den Nutzer, um Benachrichtigungen zu testen.\n"
            f"Anforderungen: Der Nutzer muss private Nachrichten aktiviert haben.\n"
            f"Verwendung:  /testnotification\n\n"
            f"`/stats`\n"
            f"Beschreibung: Zeigt Statistiken zu aktiven und abgeschlossenen Benachrichtigungen sowie die Top 5 gesuchten Arten.\n"
            f"Anforderungen: Nur Administratoren können diesen Befehl ausführen.\n"
            f"Verwendung:  /stats\n\n"
            f"`/system`\n"
            f"Beschreibung: Zeigt die Uptime an und den Status der DB.\n"
            f"Anforderungen: Nur Administratoren können diesen Befehl ausführen.\n"
            f"Verwendung:  /system"
        )

        await ctx.respond(help_message)

    except Exception as e:
        logging.error(f"Fehler im /help-Befehl: {e}")
        await ctx.respond("❌ Fehler beim Abrufen der Hilfen")

    finally:
        logging.info("Der /help-Befehl wurde ausgeführt.")

# Automatisierte Aufgaben
@tasks.loop(hours=24)
async def clean_old_notifications():
    try:
        cutoff = datetime.now() - timedelta(days=365)
        cursor.execute("UPDATE notifications SET status='expired' WHERE created_at < ? AND status='active'",
                       (cutoff.strftime('%Y-%m-%d'),))
        conn.commit()
        logging.info(f"Alte Benachrichtigungen vor {cutoff.date()} als 'expired' markiert")
    except Exception as e:
        logging.error(f"Fehler bei Bereinigung: {e}")

@tasks.loop(minutes=5)
async def check_availability():
    cursor.execute("SELECT user_id, species, regions FROM notifications WHERE status='active'")
    for user_id, species, regions in cursor.fetchall():
        await trigger_availability_check(user_id, species, regions)

@tasks.loop(seconds=60)
async def update_bot_status():
    current_time = datetime.now()
    uptime = current_time - bot.start_time

    uptime_days = uptime.days
    uptime_hours, remainder = divmod(uptime.seconds, 3600)
    uptime_minutes, _ = divmod(remainder, 60)

    server_count = len(bot.guilds)
    user_count = sum(guild.member_count for guild in bot.guilds)

    status_message = (
        f"Uptime: {uptime_days}d {uptime_hours}h {uptime_minutes}m | "
        f"{server_count} Servers | {user_count} Users"
    )

    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=status_message))

# Bot-Events
@bot.event
async def on_ready():
    bot.start_time = datetime.now()
    logging.info(f"Bot eingeloggt als {bot.user.name}")
    await bot.sync_commands()
    print([command.name for command in bot.application_commands])
    clean_old_notifications.start()
    check_availability.start()
    update_bot_status.start()

# Bot starten
if __name__ == "__main__":
    bot.run(TOKEN)
