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
    logger.setLevel(logging.DEBUG)

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

        stats_msg = (
            f"**📊 Statistik**\n"
            f"Aktive Benachrichtigungen: {active}\n"
            f"Abgeschlossene Benachrichtigungen: {completed}\n"
            f"Abgelaufene Benachrichtigungen: {expired}\n"
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
        cursor.execute("SELECT species, regions, status, created_at FROM notifications WHERE user_id=? ORDER BY created_at DESC", (str(ctx.author.id),))
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
            if entry[2] == "completed":
                grouped_history["completed"].append(entry)
            elif entry[2] == "expired":
                grouped_history["expired"].append(entry)
            elif entry[2] == "active":
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
                history_msg += f"- {entry[0]} in {entry[1]} ({entry[3].split()[0]})\n"

            if remaining_count > 0:
                history_msg += f"  ...und {remaining_count} weitere\n"

        await ctx.respond(history_msg)
    except Exception as e:
        logging.error(f"Fehler in history: {e}")
        await ctx.respond("Fehler beim Abrufen der Historie")

@bot.slash_command(name="notification", description="Richte eine Benachrichtigung ein")
async def notification(ctx, species: str, regions: str):
    regions_list = [r.strip() for r in regions.split(",")]
    valid_regions = [r for r in regions_list if any(s["country"] == r for s in SHOP_DATA.values())]

    if not valid_regions:
        await ctx.respond("❌ Ungültige Regionen angegeben")
        return

    if species_exists(species):
        try:
            cursor.execute("INSERT INTO notifications (user_id, species, regions) VALUES (?, ?, ?)",
                          (str(ctx.author.id), species, ",".join(valid_regions)))
            conn.commit()
            await ctx.respond(f"🔔 Benachrichtigung für **{species}** in {', '.join(valid_regions)} eingerichtet")
            await trigger_availability_check(ctx.author.id, species, ",".join(valid_regions))
        except sqlite3.IntegrityError:
            await ctx.respond("❌ Diese Benachrichtigung existiert bereits")
    else:
        await ctx.respond("❌ Art nicht gefunden")

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

        system_message = (
            f"**🤖 Bot-Status**\n"
            f"Uptime: {str(timedelta(seconds=uptime.total_seconds()))}\n\n"
            f"**🔍 Datenbankstatus:** {integrity_check}\n"
            f"Gesamte Benachrichtigungen in der DB: {total_notifications}\n\n"
        )

        await ctx.respond(system_message)
    except Exception as e:
        logging.error(f"Fehler im /system-Befehl: {e}")
        await ctx.respond("❌ Fehler beim Abrufen des Status")

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

    status_message = f"Uptime: {uptime_days}d {uptime_hours}h {uptime_minutes}m"

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