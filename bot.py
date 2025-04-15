#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File: bot.py
Author: Jonas Beier
Date: 2025-04-15
Version: 2.0
Description:
    Dieses Skript implementiert einen Discord-Bot mit verschiedenen Funktionen,
    darunter Benachrichtigungen, Statistiken und Systemstatus. Es verwendet SQLite
    zur Speicherung von Benachrichtigungen und JSON-Dateien für Shop-Daten.
    Unterstützt Mehrsprachigkeit (de/en), Server- und Benutzereinstellungen sowie
    kanalgebundene Befehle.

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
import asyncio
import psutil
import platform
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Pfade und Konfiguration
BASE_DIR = Path(__file__).parent
LOCALES_DIR = BASE_DIR / "locales"
TOKEN = "TOKEN"
DATA_DIRECTORY = "PFAD"
SHOPS_DATA_FILE = "shops_data.json"

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = discord.Bot(intents=intents)

# Log konfiguieren
def setup_logger():
    log_file = BASE_DIR / f"bot_log_{datetime.now().strftime('%Y%m%d')}.log"
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

# Datenbankverbindung
conn = sqlite3.connect(BASE_DIR / "antcheckbot.db")
cursor = conn.cursor()

# Tabellen erstellen
cursor.executescript("""
CREATE TABLE IF NOT EXISTS server_settings (
    server_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    language TEXT DEFAULT 'en'
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY,
    language TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    species TEXT,
    regions TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notified_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS global_stats (
    key TEXT PRIMARY KEY,
    value INTEGER DEFAULT 0
);

INSERT OR IGNORE INTO global_stats (key, value) VALUES ('deleted_notifications', 0);
""")
conn.commit()

# Spracheinstellungen
class Localization:
    def __init__(self):
        self.languages = {}
        self.load_languages()

    def load_languages(self):
        for file in LOCALES_DIR.glob("*.json"):
            lang = file.stem
            with open(file, 'r', encoding='utf-8') as f:
                self.languages[lang] = json.load(f)

    def get(self, key, lang='en', **kwargs):
        try:
            text = self.languages[lang][key]
            return text.format(**kwargs)
        except KeyError:
            return self.languages['en'][key].format(**kwargs)

l10n = Localization()

def get_user_lang(user_id, server_id):
    cursor.execute("SELECT language FROM user_settings WHERE user_id=?", (user_id,))
    if user_lang := cursor.fetchone():
        return user_lang[0]

    cursor.execute("SELECT language FROM server_settings WHERE server_id=?", (server_id,))
    if server_lang := cursor.fetchone():
        return server_lang[0]

    return 'en'

# Hilfefunktionen und Decorators
def get_server_channel(server_id):
    cursor.execute("SELECT channel_id FROM server_settings WHERE server_id=?", (server_id,))
    result = cursor.fetchone()
    return result[0] if result else None

def allowed_channel():
    async def predicate(ctx):
        if ctx.guild is None:
            return True
        allowed_channel_id = get_server_channel(ctx.guild.id)
        if allowed_channel_id is None or ctx.channel.id == allowed_channel_id:
            return True
        lang = get_user_lang(ctx.author.id, ctx.guild.id)
        await ctx.respond(l10n.get('wrong_channel', lang), ephemeral=True)
        return False
    return commands.check(predicate)

def admin_or_manage_messages():
    async def predicate(ctx):
        perms = ctx.author.guild_permissions
        return perms.administrator or perms.manage_messages
    return commands.check(predicate)

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

def get_file_age(filename):
    try:
        modified = os.path.getmtime(filename)
        age = datetime.now() - datetime.fromtimestamp(modified)
        days = age.days
        hours, remainder = divmod(age.seconds, 3600)
        minutes = remainder // 60
        return f"{days}d {hours}h {minutes}m", datetime.fromtimestamp(modified).strftime('%Y-%m-%d %H:%M:%S')
    except FileNotFoundError:
        return None, "File not found"

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

SHOP_DATA = {}
def load_shop_data():
    try:
        with open(SHOPS_DATA_FILE, "r") as f:
            shops = json.load(f)
            return {shop["id"]: shop for shop in shops}
    except FileNotFoundError:
        logging.error(f"{SHOPS_DATA_FILE} not found.")
        return {}

SHOP_DATA = load_shop_data()

async def trigger_availability_check(user_id, species, regions):
    try:
        server_id = None
        lang = get_user_lang(user_id, server_id)
        regions_list = regions.split(",")

        available = check_availability_for_species(species, regions_list)
        if available:
            user = await bot.fetch_user(int(user_id))

            header = l10n.get('availability_header', lang, species=species)
            message = f"{header}\n\n"

            for product in available:
                message += l10n.get(
                    'availability_entry',
                    lang,
                    species=product['species'],
                    shop=product['shop_name'],
                    min_price=product['min_price'],
                    max_price=product['max_price'],
                    currency=product['currency_iso'],
                    product_url=product['antcheck_url'],
                    shop_url=product['shop_url']
                ) + "\n\n"

            try:
                await user.send(message)
                cursor.execute("""
                    UPDATE notifications 
                    SET status='completed', notified_at=CURRENT_TIMESTAMP 
                    WHERE user_id=? AND species=?
                """, (user_id, species))
                conn.commit()
            except discord.Forbidden:
                logging.warning(f"DM failed for user {user_id}")

    except Exception as e:
        logging.error(f"Error in trigger_availability_check: {e}")

# Befehle
@bot.slash_command(name="startup", description="Set the server language and where the bot should respond")
@admin_or_manage_messages()
async def setup_server(
    ctx,
    language: discord.Option(str, choices=["de", "en"], default="en")
):
    server_id = ctx.guild.id
    channel_id = ctx.channel.id

    cursor.execute("""
    INSERT INTO server_settings (server_id, channel_id, language)
    VALUES (?, ?, ?)
    ON CONFLICT(server_id) DO UPDATE SET
        channel_id=excluded.channel_id,
        language=excluded.language
    """, (server_id, channel_id, language))
    conn.commit()

    await ctx.respond(l10n.get('server_setup_success', language, channel=ctx.channel.mention))

@bot.slash_command(name="usersetting", description="Set your language")
@allowed_channel()
async def set_user_language(
    ctx,
    language: discord.Option(str, choices=["de", "en"], default="en")
):
    user_id = ctx.author.id
    cursor.execute("""
    INSERT INTO user_settings (user_id, language)
    VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET language=excluded.language
    """, (user_id, language))
    conn.commit()
    await ctx.respond(l10n.get('user_setting_success', language), ephemeral=True)

@bot.slash_command(name="notification", description="Set up your notifications")
@allowed_channel()
async def notification(
    ctx,
    species: str,
    regions: str,
    force: bool = False
):
    server_id = ctx.guild.id if ctx.guild else None
    lang = get_user_lang(ctx.author.id, server_id)

    regions_list = [r.strip().lower() for r in regions.split(",")]
    valid_regions = [r for r in regions_list if any(s["country"].lower() == r for s in SHOP_DATA.values())]

    if not valid_regions:
        available_regions = sorted({s["country"].lower() for s in SHOP_DATA.values()})
        available_regions_str = ", ".join(available_regions)
        await ctx.respond(l10n.get('invalid_regions', lang, regions=available_regions_str), ephemeral=True)
        return

    species_found = species_exists(species)

    if species_found or force:
        try:
            cursor.execute("""
            INSERT INTO notifications (user_id, species, regions)
            VALUES (?, ?, ?)
            """, (str(ctx.author.id), species, ",".join(valid_regions)))
            conn.commit()

            response_key = 'notification_set_forced' if not species_found else 'notification_set'
            await ctx.respond(l10n.get(response_key, lang, species=species, regions=", ".join(valid_regions)))

            await trigger_availability_check(ctx.author.id, species, ",".join(valid_regions))
        except sqlite3.IntegrityError:
            await ctx.respond(l10n.get('notification_exists', lang), ephemeral=True)
    else:
        await ctx.respond(l10n.get('species_not_found', lang), ephemeral=True)

@bot.slash_command(name="delete_notifications", description="Delete your notifications")
@allowed_channel()
async def delete_notifications(ctx, ids: str):
    server_id = ctx.guild.id if ctx.guild else None
    lang = get_user_lang(ctx.author.id, server_id)

    try:
        id_list = [int(i.strip()) for i in ids.split(",") if i.strip().isdigit()]
        if not id_list:
            await ctx.respond(l10n.get('invalid_ids', lang), ephemeral=True)
            return

        cursor.execute(
            f"SELECT id FROM notifications WHERE user_id=? AND id IN ({','.join(['?']*len(id_list))})",
            (str(ctx.author.id), *id_list)
        )
        user_ids = [row[0] for row in cursor.fetchall()]

        if not user_ids:
            await ctx.respond(l10n.get('no_permission', lang), ephemeral=True)
            return

        cursor.execute(
            f"DELETE FROM notifications WHERE user_id=? AND id IN ({','.join(['?']*len(user_ids))})",
            (str(ctx.author.id), *user_ids)
        )

        cursor.execute(
            "UPDATE global_stats SET value = value + ? WHERE key = 'deleted_notifications'",
            (len(user_ids),)
        )
        conn.commit()

        await ctx.respond(l10n.get('deleted_success', lang, ids=", ".join(map(str, user_ids))))
    except Exception as e:
        logging.error(f"Deleteerror: {e}")
        await ctx.respond(l10n.get('delete_error', lang), ephemeral=True)

@bot.slash_command(name="stats", description="Show relevant statistics")
@allowed_channel()
@admin_or_manage_messages()
async def stats(ctx):
    server_id = ctx.guild.id if ctx.guild else None
    lang = get_user_lang(ctx.author.id, server_id)

    try:
        cursor.execute("SELECT COALESCE(COUNT(*), 0) FROM notifications WHERE status='active'")
        active = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(COUNT(*), 0) FROM notifications WHERE status='completed'")
        completed = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(COUNT(*), 0) FROM notifications WHERE status='expired'")
        expired = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COALESCE(species, 'unknown'), COUNT(*)
            FROM notifications
            GROUP BY species
            ORDER BY COUNT(*) DESC
            LIMIT 5
        """)
        top_species = cursor.fetchall()

        cursor.execute("""
            SELECT COALESCE(value, 0)
            FROM global_stats
            WHERE key = 'deleted_notifications'
        """)
        deleted_total = cursor.fetchone()[0]

        logging.info(
            f"Stats values - Active: {active}, Completed: {completed}, "
            f"Expired: {expired}, Deleted: {deleted_total}, "
            f"Top Species: {top_species}"
        )

        if not top_species:
            top_species = [(l10n.get('no_data', lang), 0)]

        try:
            stats_msg = l10n.get(
                'stats_message',
                lang,
                active=active,
                completed=completed,
                expired=expired,
                deleted_total=deleted_total,
                top_species="\n".join([f"- {s[0]}: {s[1]}" for s in top_species])
            )
        except KeyError as e:
            logging.error(f"Missing localization key: {e}")
            stats_msg = l10n.get('stats_error', lang)

        await ctx.respond(stats_msg)

    except sqlite3.Error as e:
        logging.error(f"Database error in stats: {e}")
        await ctx.respond(l10n.get('stats_db_error', lang))
    except Exception as e:
        logging.error(f"Unexpected error in stats: {e}", exc_info=True)
        await ctx.respond(l10n.get('stats_error', lang))

@bot.slash_command(name="history", description="Show your requests")
@allowed_channel()
async def history(ctx):
    server_id = ctx.guild.id if ctx.guild else None
    lang = get_user_lang(ctx.author.id, server_id)

    try:
        cursor.execute("SELECT id, species, regions, status, created_at, notified_at FROM notifications WHERE user_id=? ORDER BY created_at DESC",
            (str(ctx.author.id),))
        history = cursor.fetchall()

        if not history:
            await ctx.respond(l10n.get('history_no_entries', lang))
            return

        grouped_history = {"completed": [], "expired": [], "active": [], "other": []}
        for entry in history:
            grouped_history[entry[3].lower() if entry[3] else "other"].append(entry)

        history_msg = l10n.get('history_header', lang) + "\n"
        status_map = {
            "completed": ("history_completed", "✅"),
            "expired": ("history_expired", "⏳"),
            "active": ("history_active", "🔄"),
            "other": ("history_other", "❓")
        }

        for status, (key, emoji) in status_map.items():
            entries = grouped_history.get(status, [])
            if not entries:
                continue

            displayed = entries[:10]
            remaining = len(entries) - 10

            history_msg += f"\n**{l10n.get(key, lang)}**\n"
            for entry in displayed:

                created_date = entry[4].split()[0]
                notified_date = entry[5].split()[0] if entry[5] else None
    
                params = {
                    'species': entry[1],
                    'regions': entry[2],
                    'created': created_date,
                    'id': entry[0]
                }
    
                if entry[3].lower() == "completed" and notified_date:
                    params['notified'] = notified_date
                    entry_msg = l10n.get('history_entry_completed', lang, **params)
                else:
                    entry_msg = l10n.get('history_entry', lang, **params)
    
                history_msg += f"- {entry_msg}\n"

            if remaining > 0:
                history_msg += l10n.get('history_more_entries', lang, count=remaining) + "\n"

        await ctx.respond(history_msg)
    except Exception as e:
        logging.error(f"Error in history: {e}")
        await ctx.respond(l10n.get('general_error', lang))

@bot.slash_command(name="system", description="Show system info")
@allowed_channel()
@commands.has_permissions(administrator=True)
async def system(ctx):
    server_id = ctx.guild.id if ctx.guild else None
    lang = get_user_lang(ctx.author.id, server_id)

    try:
        uptime = datetime.now() - bot.start_time
        cursor.execute("SELECT COUNT(*) FROM notifications")
        total = cursor.fetchone()[0]
        integrity = cursor.execute("PRAGMA integrity_check").fetchone()[0]

        age, modified = get_file_age(SHOPS_DATA_FILE)
        if age is None:
            file_status = l10n.get('system_file_missing', lang)
        else:
            file_status = l10n.get('system_file_status', lang,
                                 modified=modified,
                                 age=age)

        await ctx.respond(l10n.get('system_status', lang,
                                 uptime=str(uptime).split('.')[0],
                                 integrity=integrity,
                                 total=total,
                                 file_status=file_status))
    except Exception as e:
        logging.error(f"Systemerror: {e}")
        await ctx.respond(l10n.get('system_error', lang))

@bot.slash_command(name="help", description="All commands")
@allowed_channel()
async def help(ctx):
    server_id = ctx.guild.id if ctx.guild else None
    lang = get_user_lang(ctx.author.id, server_id)

    try:
        commands = "\n".join([
            l10n.get('help_notification', lang),
            l10n.get('help_history', lang),
            l10n.get('help_test', lang),
            l10n.get('help_delete', lang),
            l10n.get('help_stats', lang),
            l10n.get('help_system', lang),
            l10n.get('help_startup', lang),
            l10n.get('help_usersetting', lang)
        ])
        await ctx.respond(l10n.get('help_full', lang, commands=commands))
    except Exception as e:
        logging.error(f"Help error: {e}")
        await ctx.respond(l10n.get('general_error', lang))

@bot.slash_command(name="testnotification", description="Test PN notifications")
@allowed_channel()
async def testnotification(ctx):
    server_id = ctx.guild.id if ctx.guild else None
    lang = get_user_lang(ctx.author.id, server_id)
    try:
        await ctx.author.send(l10n.get('testnotification_dm', lang))
        await ctx.respond(l10n.get('testnotification_success', lang), ephemeral=True)
    except discord.Forbidden:
        await ctx.respond(l10n.get('testnotification_forbidden', lang), ephemeral=True)

# Automatisierte Aufgaben
@tasks.loop(hours=24)
async def clean_old_notifications():
    try:
        cutoff = datetime.now() - timedelta(days=365)
        cursor.execute("UPDATE notifications SET status='expired' WHERE created_at < ? AND status='active'",
                      (cutoff.strftime('%Y-%m-%d'),))
        conn.commit()
        logging.info(f"Old notifications cleaned up")
    except Exception as e:
        logging.error(f"Error during cleanup: {e}")

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
        f"{server_count} Servers | {user_count} Users | "
        f"Bot-Version 2.0"
    )
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=status_message))

@bot.event
async def on_ready():
    bot.start_time = datetime.now()
    logging.info(f"Bot online: {bot.user.name}")
    await bot.sync_commands()
    clean_old_notifications.start()
    check_availability.start()
    update_bot_status.start()

if __name__ == "__main__":
    LOCALES_DIR.mkdir(exist_ok=True)
    bot.run(TOKEN)