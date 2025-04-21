#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File: bot.py
Author: Jonas Beier
Date: 2025-04-18
Version: 3.5
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
from thefuzz import process

# Pfade und Konfiguration
BASE_DIR = Path(__file__).parent
LOCALES_DIR = BASE_DIR / "locales"
TOKEN = "TOKEN"
DATA_DIRECTORY = "DIR"
SHOPS_DATA_FILE = "shops_data.json"
SERVER_IDS = [ID1, ID2]
BOT_OWNER = USERID

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True
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

CREATE TABLE IF NOT EXISTS shops (
    id TEXT PRIMARY KEY,
    name TEXT,
    country TEXT,
    url TEXT,
    average_rating REAL
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

CREATE TABLE IF NOT EXISTS server_user_mappings (
    user_id TEXT,
    server_id INTEGER,
    PRIMARY KEY (user_id, server_id)
);

CREATE TABLE IF NOT EXISTS user_shop_blacklist (
    user_id TEXT,
    shop_id TEXT,
    PRIMARY KEY (user_id, shop_id),
    FOREIGN KEY (user_id) REFERENCES notifications(user_id),
    FOREIGN KEY (shop_id) REFERENCES shops(id)
);

CREATE TABLE IF NOT EXISTS shop_name_mappings (
    external_name TEXT PRIMARY KEY,
    shop_id TEXT,
    FOREIGN KEY (shop_id) REFERENCES shops(id)
);

CREATE TABLE IF NOT EXISTS server_info (
    server_id INTEGER PRIMARY KEY,
    server_name VARCHAR(100) NOT NULL,
    member_count INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL,
    icon_url TEXT,
    splash_url TEXT,
    banner_url TEXT,
    description TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_notification
ON notifications(user_id, species, regions) WHERE status='active';

CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);

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
            return self.languages[lang][key].format(**kwargs)
        except KeyError as e:
            logging.error(f"Missing placeholder {e} for key '{key}'")
            return f"[ERROR: Missing data for {key}]"

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
        return False
    return commands.check(predicate)

def admin_or_manage_messages():
    async def predicate(ctx):
        perms = ctx.author.guild_permissions
        return perms.administrator or perms.manage_messages
    return commands.check(predicate)

def species_exists(species):
    for filename in os.listdir(DATA_DIRECTORY):
        if filename.startswith("products_shop_") and filename.endswith(".json"):
            file_path = os.path.join(DATA_DIRECTORY, filename)
            try:
                shop_id_from_filename = int(filename.split("_")[2].split(".")[0])
            except Exception:
                shop_id_from_filename = "unbekannt"
            if not os.path.exists(file_path):
                logging.warning(f"Product file '{file_path}' does not exist. Skip store ID {shop_id_from_filename}.")
                continue
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

def check_availability_for_species(species, regions, user_id=None):
    logger = logging.getLogger("availability")
    logger.info(f"Start availability check for Art: '{species}', Regions: {regions}, User: {user_id}")

    blacklisted_shops = set()
    if user_id is not None:
        blacklisted_shops = get_blacklisted_shops(user_id)
        logger.debug(f"Blacklist for users {user_id}: {blacklisted_shops}")

    try:
        with open("shops_data.json", "r", encoding="utf-8") as f:
            shops_list = json.load(f)
        SHOP_DATA = {shop["id"]: shop for shop in shops_list}
        logger.info(f"{len(SHOP_DATA)} Shops geladen.")
        logger.debug(f"Loaded store IDs: {list(SHOP_DATA.keys())}")
    except Exception as e:
        logger.error(f"Error loading the store data: {e}", exc_info=True)
        return []

    available_products = []
    species_cf = species.strip().casefold()

    for filename in os.listdir(DATA_DIRECTORY):
        if filename.startswith("products_shop_") and filename.endswith(".json"):
            file_path = os.path.join(DATA_DIRECTORY, filename)

            try:
                shop_id_from_filename = int(filename.split("_")[2].split(".")[0])
                logger.debug(f"File name: {filename}, extracted store ID: {shop_id_from_filename}")
            except Exception as e:
                logger.warning(f"File name '{filename}' could not be parsed: {e}")
                continue

            shop_data = SHOP_DATA.get(shop_id_from_filename)
            if not shop_data:
                logger.warning(f"No store data record for store ID '{shop_id_from_filename}' found.")
                continue

            shop_country = shop_data.get("country", "").lower()
            if shop_country not in [r.lower() for r in regions]:
                logger.debug(f"Shop '{shop_data['name']}' ({shop_country}) not in target regions {regions}.")
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except FileNotFoundError:
                logger.warning(f"Product file '{file_path}' does not exist.")
                continue
            except Exception as e:
                logger.error(f"Error loading the product file '{file_path}': {e}", exc_info=True)
                continue

            for product in data:
                title = product.get("title", "").strip()
                title_cf = title.casefold()
                in_stock = product.get("in_stock", False)
                product_shop_id = product.get("shop_id")

                logger.debug(f"Check product: '{title}' | In Stock: {in_stock} | Shop-ID: {product_shop_id}")

                if not title_cf.startswith(species_cf):
                    logger.debug(f"Product '{title}' does not match search term '{species}' (startswith).")
                    continue

                if not in_stock:
                    logger.debug(f"Product '{title}' not in stock.")
                    continue

                if product_shop_id in blacklisted_shops:
                    logger.info(f"Shop '{product_shop_id}' for User {user_id} on blacklist, skipped.")
                    continue

                logger.info(f"Product available: '{title}' bei '{shop_data['name']}' ({shop_country}).")
                available_products.append({
                    "species": title,
                    "shop_name": shop_data["name"],
                    "min_price": product["min_price"],
                    "max_price": product["max_price"],
                    "currency_iso": product["currency_iso"],
                    "antcheck_url": product["antcheck_url"],
                    "shop_url": shop_data["url"],
                    "shop_id": shop_id_from_filename
                })

    logger.info(f"Availability check completed. {len(available_products)} Products found.")
    return available_products

def reload_shops():
    global SHOP_DATA
    try:
        with open(SHOPS_DATA_FILE, "r") as f:
            shops = json.load(f)
            SHOP_DATA = {shop["id"]: shop for shop in shops}
            for shop in SHOP_DATA.values():
                cursor.execute("""
                    INSERT OR REPLACE INTO shops (id, name, country, url)
                    VALUES (?, ?, ?, ?)
                """, (shop["id"], shop["name"], shop["country"], shop["url"]))
            conn.commit()
            logging.info("Shop data reloaded and database updated.")
    except Exception as e:
        logging.error(f"Error reloading shop data: {e}")

def load_shop_data():
    global SHOP_DATA
    try:
        cursor.execute("""
            SELECT id, name, country, url, average_rating
            FROM shops
        """)
        SHOP_DATA = {
            row[0]: {
                "id": row[0],
                "name": row[1],
                "country": row[2],
                "url": row[3],
                "average_rating": row[4]
            } for row in cursor.fetchall()
        }
        logging.info(f"{len(SHOP_DATA)} Stores loaded from DB")
    except Exception as e:
        logging.error(f"Error when loading the stores: {e}")
    return SHOP_DATA

SHOP_DATA = load_shop_data()

def load_shop_data_from_google_sheets():
    import os
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
    SPREADSHEET_ID = '1Ymc8M5GHwfKbdh0QMRhZhL5zUK2wMRua0vk6v1MxiYE'
    RANGE_NAME = 'Händler A-Z!A2:C'

    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        values = result.get('values', [])
        print(values)
        if not values:
            print('No data found.')
            return []
        return values
    except HttpError as err:
        print(f'An error occurred: {err}')
        return []

def split_message(text, max_length=2000):
    lines = text.split('\n')
    blocks = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > max_length:
            blocks.append(current)
            current = ""
        current += line + "\n"
    if current:
        blocks.append(current)
    return blocks

def get_blacklisted_shops(user_id):
    cursor.execute(
        "SELECT shop_id FROM user_shop_blacklist WHERE user_id=?",
        (user_id,)
    )
    return set(row[0] for row in cursor.fetchall())

def get_shop_rating(shop_id):
    cursor.execute("SELECT average_rating FROM shops WHERE id = ?", (shop_id,))
    result = cursor.fetchone()
    return result[0] if result else None

def owner_only():
    async def predicate(ctx):
        return ctx.author.id == BOT_OWNER
    return commands.check(predicate)

def get_guild_info(guild):
    return (
        guild.id,
        guild.name,
        guild.member_count,
        guild.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        str(guild.icon.url) if guild.icon else None,
        str(guild.splash.url) if guild.splash else None,
        str(guild.banner.url) if guild.banner else None,
        guild.description or None
    )

async def update_server_info(guild):
    data = get_guild_info(guild)

    cursor.execute("""
        INSERT INTO server_info (
            server_id, server_name, member_count,
            created_at, icon_url, splash_url,
            banner_url, description
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(server_id) DO UPDATE SET
            server_name=excluded.server_name,
            member_count=excluded.member_count,
            created_at=excluded.created_at,
            icon_url=excluded.icon_url,
            splash_url=excluded.splash_url,
            banner_url=excluded.banner_url,
            description=excluded.description
    """, data)
    conn.commit()
    
async def remove_left_servers(bot):
    current_guild_ids = {guild.id for guild in bot.guilds}
    cursor.execute("SELECT server_id FROM server_info")
    db_guild_ids = {row[0] for row in cursor.fetchall()}
    left_guild_ids = db_guild_ids - current_guild_ids
    for guild_id in left_guild_ids:
        cursor.execute("DELETE FROM server_info WHERE server_id = ?", (guild_id,))
    conn.commit()

async def trigger_availability_check(user_id, species, regions):
    try:
        server_id = None
        lang = get_user_lang(user_id, server_id)
        regions_list = regions.split(",") if isinstance(regions, str) else regions

        try:
            available = check_availability_for_species(species, regions_list, user_id=str(user_id))
        except FileNotFoundError as e:
            logging.error(f"Missing product file: {e.filename}")
            return
        except Exception as e:
            logging.error(f"Error during availability check: {e}", exc_info=True)
            return

        if not available:
            logging.info(f"No available products for {species} in {regions}")
            return

        user = None
        try:
            user = await bot.fetch_user(int(user_id))
        except discord.NotFound:
            logging.error(f"User {user_id} not found.")
            return
        except discord.HTTPException as e:
            logging.error(f"HTTP-Error: {e}")
            return

        if not user:
            logging.error(f"User {user_id} is None")
            return

        header = l10n.get('availability_header', lang, species=species)
        message = [header + "\n"]

        for product in available:
            shop_id = product['shop_id']
            rating = get_shop_rating(product['shop_id'])
            rating_str = f"⭐ {rating:.2f}" if rating else "❌"

            message.append(l10n.get(
                'availability_entry',
                lang,
                species=product['species'],
                shop=product['shop_name'],
                min_price=product['min_price'],
                max_price=product['max_price'],
                currency=product['currency_iso'],
                product_url=product['antcheck_url'],
                shop_url=product['shop_url'],
                rating=rating_str
            ))

        try:
            await user.send("\n\n".join(message))
            cursor.execute("""
                UPDATE notifications
                SET status='completed', notified_at=CURRENT_TIMESTAMP
                WHERE user_id=? AND species=?
            """, (user_id, species))
            conn.commit()

        except discord.Forbidden:
            logging.warning(f"DM failed for user {user_id}")
            await handle_dm_failure(user_id, species, regions, lang)
        except discord.HTTPException as e:
            if hasattr(e, "status") and e.status == 429:
                logging.warning(f"Rate limit reached: {e}")
                await asyncio.sleep(e.retry_after)
            else:
                raise
        except Exception as e:
            logging.error(f"Error when sending the message: {e}")

    except Exception as e:
        logging.error(f"Critical error: {e}", exc_info=True)
        cursor.execute("""
            UPDATE notifications
            SET status='failed'
            WHERE user_id=? AND species=?
        """, (user_id, species))
        conn.commit()

async def handle_dm_failure(user_id, species, regions, lang):
    try:
        cursor.execute("""
            SELECT DISTINCT server_id FROM server_user_mappings
            WHERE user_id=?
        """, (user_id,))
        servers = cursor.fetchall()

        for (server_id,) in servers:
            channel_id = get_server_channel(server_id)
            channel = bot.get_channel(channel_id) if channel_id else None

            if not channel:
                guild = bot.get_guild(server_id)
                channel = guild.system_channel if guild else None

            if channel:
                try:
                    await channel.send(
                        f"<@{user_id}>, {l10n.get('dm_failed', lang)}\n"
                        f"**Art:** {species}\n"
                        f"**Regions:** {', '.join(regions)}"
                    )
                except discord.HTTPException as e:
                    if hasattr(e, "status") and e.status == 429:
                        logging.warning(f"Rate limit in channel {server_id}: {e}")
                        await asyncio.sleep(e.retry_after)
                    else:
                        raise

    except Exception as e:
        logging.error(f"Error with DM fallback: {e}")

async def notify_expired(user_id, species, regions, lang):
    try:
        user = await bot.fetch_user(int(user_id))
        msg = l10n.get('notification_expired_dm', lang, species=species, regions=regions)
        await user.send(msg)
    except discord.Forbidden:
        logging.warning(f"DM failed for expired notification to user {user_id}")
    except Exception as e:
        logging.error(f"Error in notify_expired: {e}")

# Befehle
@bot.slash_command(name="startup",description="Set the server language and where the bot should respond (only Admin/Mod)")
@admin_or_manage_messages()
async def setup_server(ctx, language: discord.Option(str, "Select the bot language (de = German, en = English, eo = Esperanto)", choices=["de", "en", "eo"], default="en"), channel: discord.Option(discord.TextChannel, "Channel for bot responses (optional)", required=False) = None):
    server_id = ctx.guild.id
    channel_id = channel.id if channel else None

    if channel_id is not None:
        cursor.execute("""
            INSERT INTO server_settings (server_id, channel_id, language)
            VALUES (?, ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                channel_id=excluded.channel_id,
                language=excluded.language
        """, (server_id, channel_id, language))
    else:
        cursor.execute("""
            INSERT INTO server_settings (server_id, language)
            VALUES (?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                language=excluded.language
        """, (server_id, language))
    conn.commit()

    await ctx.respond(
    l10n.get(
        'server_setup_success',
        language,
        channel=channel.mention if channel else l10n.get('all_channels', language)))

user_settings = bot.create_group(
    name="usersetting",
    description="Set your language or shop blacklist"
)

@user_settings.command(description="Set your language")
@allowed_channel()
async def language(ctx, language: discord.Option(str, "Select the bot language (de = German, en = English, eo = Esperanto)", choices=["de", "en", "eo"], default="en")):
    user_id = ctx.author.id
    cursor.execute("""
    INSERT INTO user_settings (user_id, language)
    VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET language=excluded.language
    """, (user_id, language))
    conn.commit()
    await ctx.respond(l10n.get('user_setting_success', language), ephemeral=True)

@user_settings.command(description="Add shop to blacklist")
@allowed_channel()
async def blacklist_add(ctx,shop: discord.Option(str, "Shop name or ID", required=True)):
    user_id = str(ctx.author.id)
    lang = get_user_lang(user_id, ctx.guild.id if ctx.guild else None)

    shop_names = {s_id: s_data["name"] for s_id, s_data in SHOP_DATA.items()}
    matches = process.extract(shop, shop_names.values(), limit=3)

    best_match = next((match for match in matches if match[1] > 80), None)
    if not best_match:
        suggestions = "\n".join([f"- {m[0]}" for m in matches])
        await ctx.respond(
            l10n.get('shop_not_found_suggest', lang, shop=shop, suggestions=suggestions),
            ephemeral=True
        )
        return

    shop_name = best_match[0]
    shop_id = next(s_id for s_id, name in shop_names.items() if name == shop_name)

    try:
        cursor.execute("""
            INSERT INTO user_shop_blacklist (user_id, shop_id)
            VALUES (?, ?)
            ON CONFLICT(user_id, shop_id) DO NOTHING
        """, (user_id, shop_id))
        conn.commit()
        await ctx.respond(
            l10n.get('blacklist_add_success', lang, shop=shop_name),
            ephemeral=True
        )
    except Exception as e:
        logging.error(f"Blacklist-Add Error: {e}")
        await ctx.respond(l10n.get('general_error', lang), ephemeral=True)

@user_settings.command(description="Remove shop from blacklist")
@allowed_channel()
async def blacklist_remove(ctx,shop: discord.Option(str, "Shop name or ID", required=True)):
    user_id = str(ctx.author.id)
    lang = get_user_lang(user_id, ctx.guild.id if ctx.guild else None)

    shop_names = {s_id: s_data["name"] for s_id, s_data in SHOP_DATA.items()}
    matches = process.extract(shop, shop_names.values(), limit=3)

    best_match = next((match for match in matches if match[1] > 80), None)
    if not best_match:
        suggestions = "\n".join([f"- {m[0]}" for m in matches])
        await ctx.respond(
            l10n.get('shop_not_found_suggest', lang, shop=shop, suggestions=suggestions),
            ephemeral=True
        )
        return

    shop_name = best_match[0]
    shop_id = next(s_id for s_id, name in shop_names.items() if name == shop_name)

    cursor.execute("""
        DELETE FROM user_shop_blacklist
        WHERE user_id=? AND shop_id=?
    """, (user_id, shop_id))
    conn.commit()

    if cursor.rowcount > 0:
        await ctx.respond(
            l10n.get('blacklist_remove_success', lang, shop=shop_name),
            ephemeral=True
        )
    else:
        await ctx.respond(l10n.get('shop_not_in_blacklist', lang), ephemeral=True)

@user_settings.command(description="List blacklisted shops")
@allowed_channel()
async def blacklist_list(ctx):
    user_id = str(ctx.author.id)
    lang = get_user_lang(user_id, ctx.guild.id if ctx.guild else None)

    cursor.execute("""
        SELECT shop_id FROM user_shop_blacklist
        WHERE user_id=?
    """, (user_id,))

    shops = []
    for row in cursor.fetchall():
        shop_id = row[0]
        if shop_id in SHOP_DATA:
            shops.append(SHOP_DATA[shop_id]["name"])

    if not shops:
        await ctx.respond(l10n.get('blacklist_empty', lang), ephemeral=True)
        return

    await ctx.respond(
        l10n.get('blacklist_list', lang, shops="\n- " + "\n- ".join(shops)),
        ephemeral=True
    )

@user_settings.command(description="List all shops")
@allowed_channel()
async def shop_list(
    ctx,
    country: discord.Option(str, "Filter shops by region code (e.g. 'de' for Germany, 'fr' for France). Leave empty to show all shops.", required=False) = None
):
    lang = get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)

    def sort_key(s):
        try:
            avg = s['average_rating']
            return (avg is None, -(avg if avg is not None else 0), s['name'].lower())
        except KeyError:
            return (True, 0, s['name'].lower())

    if country:
        shops_filtered = [s for s in SHOP_DATA.values() if s.get("country", "").lower() == country.lower()]
    else:
        shops_filtered = list(SHOP_DATA.values())

    shops_sorted = sorted(shops_filtered, key=sort_key)

    shops = []
    for s in shops_sorted:
        try:
            avg = s['average_rating']
            rating_str = f"⭐ {avg:.2f}" if avg is not None else "❌"
        except KeyError:
            rating_str = "❌"
        shops.append(f"`{s['id']}` | {s['name']} - {rating_str}")

    if not shops:
        await ctx.respond(l10n.get('no_shops_found', lang), ephemeral=True)
        return

    text = l10n.get('available_shops', lang, shops="\n- " + "\n- ".join(shops))
    blocks = split_message(text)

    await ctx.respond(blocks[0], ephemeral=True)
    for block in blocks[1:]:
        await ctx.followup.send(block, ephemeral=True)

@bot.slash_command(name="notification", description="Set up your notifications")
@allowed_channel()
async def notification(ctx, species: discord.Option(str, "Which species do you want to be notified about?"), regions: discord.Option(str, "For which regions do you want notifications?"), force: discord.Option(bool, "Force notification even if already set", default=False)):
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
                INSERT INTO notifications (user_id, species, regions, status)
                VALUES (?, ?, ?, 'active')
                ON CONFLICT(user_id, species, regions) WHERE status='active'
                DO UPDATE SET created_at=CURRENT_TIMESTAMP
            """, (str(ctx.author.id), species, ",".join(valid_regions)))

            is_new = cursor.rowcount == 1

            if is_new:
                response_key = 'notification_set_forced' if not species_found else 'notification_set'
            else:
                response_key = 'notification_reactivated'

            await ctx.respond(l10n.get(response_key, lang, species=species, regions=", ".join(valid_regions)))
            await asyncio.sleep(1)

            if server_id:
                cursor.execute("""
                    INSERT OR IGNORE INTO server_user_mappings (user_id, server_id)
                    VALUES (?, ?)
                """, (str(ctx.author.id), server_id))

            conn.commit()

            response_key = 'notification_set_forced' if not species_found else 'notification_set'
            await ctx.respond(l10n.get(response_key, lang, species=species, regions=", ".join(valid_regions)))
            await ctx.followup.send(l10n.get('checking_availability', lang, species=species))
            await trigger_availability_check(ctx.author.id, species, ",".join(valid_regions))

        except sqlite3.IntegrityError:
            if force:
                cursor.execute("""
                    UPDATE notifications
                    SET created_at=CURRENT_TIMESTAMP
                    WHERE user_id=? AND species=? AND regions=? AND status='active'
                """, (str(ctx.author.id), species, ",".join(valid_regions)))
                conn.commit()

                if cursor.rowcount > 0:
                    await ctx.respond(l10n.get('notification_reactivated', lang, species=species, regions=regions))
                else:
                    try:
                        cursor.execute("""
                            INSERT INTO notifications (user_id, species, regions, status)
                            VALUES (?, ?, ?, 'active')
                        """, (str(ctx.author.id), species, ",".join(valid_regions)))
                        conn.commit()
                        await ctx.respond(l10n.get('notification_set_forced', lang, species=species))
                    except sqlite3.IntegrityError:
                        await ctx.respond(l10n.get('notification_exists_active', lang, species=species, regions=regions, ephemeral=True))
            else:
                await ctx.respond(l10n.get('notification_exists_active', lang, species=species, regions=regions, ephemeral=True))

    else:
        await ctx.respond(l10n.get('species_not_found', lang), ephemeral=True)

@bot.slash_command(name="delete_notifications", description="Delete your notifications")
@allowed_channel()
async def delete_notifications(ctx, ids: discord.Option(str, "Enter the IDs of the notifications to delete (comma-separated)")):
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

@bot.slash_command(name="stats", description="Show relevant statistics (only Admin/Mod)")
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

@bot.slash_command(name="system", description="Show system info (only Admin/Mod)")
@allowed_channel()
@admin_or_manage_messages()
async def system(ctx):
    server_id = ctx.guild.id if ctx.guild else None
    lang = get_user_lang(ctx.author.id, server_id)
    server_count = len(bot.guilds)
    user_count = sum(guild.member_count for guild in bot.guilds)

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

        latency = f"{bot.latency * 1000:.2f}"
        cpu = f"{psutil.cpu_percent(interval=1):.1f}"
        ram = f"{psutil.virtual_memory().percent:.1f}"
        system_info = f"{platform.system()} {platform.release()}"

        msg = l10n.get('system_status', lang,
                       uptime=str(uptime).split('.')[0],
                       servers=server_count,
                       users=user_count,
                       integrity=integrity,
                       total=total,
                       file_status=file_status)

        perf_msg = l10n.get('system_performance', lang,
                            latency=latency,
                            cpu=cpu,
                            ram=ram,
                            system=system_info)

        await ctx.respond(f"{msg}\n\n{perf_msg}")

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
            l10n.get('help_usersetting', lang),
            l10n.get('help_reloadshops', lang),
            l10n.get('help_shopmapping', lang),
            l10n.get('help_showservers', lang)
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

@bot.slash_command(name="reloadshops", description="Reload shop data from JSON file (only Admin/Mod)")
@admin_or_manage_messages()
@allowed_channel()
async def reloadshops(ctx):
    reload_shops()
    await ctx.respond("Store data has been reloaded.", ephemeral=True)

shopmapping = bot.create_group(
    name="shopmapping",
    description="Manage shop name mappings for Google Sheets imports! (only for AAM-Discord)",
    guild_ids=SERVER_IDS
)

@shopmapping.command(name="add", description="Assign external shop name to internal ID (only for AAM-Discord)")
@admin_or_manage_messages()
async def shopmapping_add(
    ctx,
    external_name: discord.Option(str, "Name from Google Sheets"),
    shop_id: discord.Option(str, "Internal shop ID")
):
    lang = get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)

    if shop_id not in SHOP_DATA:
        await ctx.respond(l10n.get("shopmapping_add_invalid_id", lang), ephemeral=True)
        return

    try:
        cursor.execute("""
            INSERT INTO shop_name_mappings (external_name, shop_id)
            VALUES (?, ?)
            ON CONFLICT(external_name) DO UPDATE SET shop_id=excluded.shop_id
        """, (external_name.strip(), shop_id))
        conn.commit()

        await ctx.respond(
            l10n.get("shopmapping_add_success", lang, external=external_name, id=shop_id, shop=SHOP_DATA[shop_id]['name']),
            ephemeral=True
        )
    except Exception as e:
        logging.error(f"Shopmapping add error: {e}")
        await ctx.respond(l10n.get("shopmapping_add_error", lang), ephemeral=True)

@shopmapping.command(name="show", description="Show all current mappings (only for AAM-Discord)")
@admin_or_manage_messages()
async def shopmapping_show(ctx):
    lang = get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
    cursor.execute("SELECT * FROM shop_name_mappings")
    mappings = cursor.fetchall()

    if not mappings:
        await ctx.respond(l10n.get("shopmapping_show_none", lang), ephemeral=True)
        return

    msg = [l10n.get("shopmapping_show_header", lang)]
    for ext_name, shop_id in mappings:
        shop_name = SHOP_DATA.get(shop_id, {}).get('name', 'Unknown')
        msg.append(l10n.get("shopmapping_show_entry", lang, external=ext_name, id=shop_id, shop=shop_name))

    await ctx.respond("\n".join(msg), ephemeral=True)

@shopmapping.command(name="remove", description="Remove a shop mapping (only for AAM-Discord)")
@admin_or_manage_messages()
async def shopmapping_remove(
    ctx,
    external_name: discord.Option(str, "Name from Google Sheets")
):
    lang = get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
    cursor.execute("DELETE FROM shop_name_mappings WHERE external_name=?", (external_name,))
    conn.commit()

    if cursor.rowcount > 0:
        await ctx.respond(l10n.get("shopmapping_remove_success", lang, external=external_name), ephemeral=True)
    else:
        await ctx.respond(l10n.get("shopmapping_remove_none", lang), ephemeral=True)

@bot.slash_command(name="serverlist", description="Shows all server information (only for bot owners)")
@owner_only()
async def serverlist(ctx):
    if ctx.author.id != BOT_OWNER:
        lang = get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
        await ctx.respond(l10n.get('no_permission', lang), ephemeral=True)
        return

    lang = get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)

    messages = []
    for guild in bot.guilds:
        info = (
            f"**{guild.name}**\n"
            f"{l10n.get('serverlist_id', lang)}: `{guild.id}`\n"
            f"{l10n.get('serverlist_members', lang)}: {guild.member_count}\n"
            f"{l10n.get('serverlist_icon', lang)}: <{guild.icon.url if guild.icon else l10n.get('serverlist_no_icon', lang)}>\n"
            f"{l10n.get('serverlist_splash', lang)}: <{guild.splash.url if guild.splash else l10n.get('serverlist_no_splash', lang)}>\n"
            f"{l10n.get('serverlist_banner', lang)}: <{guild.banner.url if guild.banner else l10n.get('serverlist_no_banner', lang)}>\n"
            f"{l10n.get('serverlist_description', lang)}: {guild.description or l10n.get('serverlist_no_description', lang)}\n"
            f"{l10n.get('serverlist_created', lang)}: {guild.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
            "---------------------------"
        )
        messages.append(info)

    for block in split_message("\n".join(messages)):
        await ctx.respond(block, ephemeral=True)

# Automatisierte Aufgaben
@tasks.loop(hours=168)
async def optimize_db():
    try:
        cursor.execute("VACUUM;")
        cursor.execute("PRAGMA optimize;")
        conn.commit()
        logging.info("VACUUM and OPTIMIZE completed successfully.")
    except Exception as e:
        logging.error(f"VACUUM/OPTIMIZE error: {e}")

@tasks.loop(hours=48)
async def sync_ratings():
    try:
        raw_data = load_shop_data_from_google_sheets()

        cursor.execute("SELECT external_name, shop_id FROM shop_name_mappings")
        all_mappings = cursor.fetchall()

        for row in raw_data:
            shop_name, _, rating = row
            shop_id = None

            for ext_name, mapped_id in all_mappings:
                if ext_name.casefold() == shop_name.casefold():
                    shop_id = mapped_id
                    break

            if not shop_id:
                matches = process.extractOne(
                    shop_name,
                    [s["name"] for s in SHOP_DATA.values()],
                    scorer=process.fuzz.token_sort_ratio
                )
                if matches and matches[1] > 75:
                    shop_id = next(k for k,v in SHOP_DATA.items() if v["name"] == matches[0])
                else:
                    continue

            cursor.execute("""
                UPDATE shops
                SET average_rating = ?
                WHERE id = ?
            """, (float(rating.replace(',', '.')), shop_id))

        conn.commit()
        load_shop_data()
    except Exception as e:
        logging.error(f"Rating sync failed: {e}")

@tasks.loop(hours=24)
async def clean_old_notifications():
    try:
        cutoff = datetime.now() - timedelta(days=365)
        cursor.execute("""
            SELECT id, user_id, species, regions
            FROM notifications
            WHERE created_at < ? AND status='active'
        """, (cutoff.strftime('%Y-%m-%d'),))
        expired = cursor.fetchall()

        cursor.execute("""
            UPDATE notifications SET status='expired'
            WHERE created_at < ? AND status='active'
        """, (cutoff.strftime('%Y-%m-%d'),))
        conn.commit()

        for notif_id, user_id, species, regions in expired:
            lang = get_user_lang(user_id, None)
            await notify_expired(user_id, species, regions, lang)

        logging.info(f"Old notifications cleaned up and users notified")
    except Exception as e:
        logging.error(f"Error during cleanup: {e}")

@tasks.loop(hours=2)
async def update_server_infos():
    for guild in bot.guilds:
        await update_server_info(guild)
    await remove_left_servers(bot)

@tasks.loop(hours=1)
async def reload_shops_task():
    reload_shops()

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
        f"Uptime: {uptime_days}d {uptime_hours}h {uptime_minutes}m")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=status_message))

@bot.event
async def on_ready():
    bot.start_time = datetime.now()
    logging.info(f"Bot online: {bot.user.name}")
    await bot.sync_commands()
    clean_old_notifications.start()
    check_availability.start()
    update_bot_status.start()
    psutil.cpu_percent(interval=None)
    optimize_db.start()
    reload_shops_task.start()
    sync_ratings.start()
    update_server_infos.start()
    logging.info(f"Bot final loaded")

@bot.event
async def on_application_command_error(ctx, error):
    if isinstance(error, discord.errors.CheckFailure):

        if not ctx.response.is_done():
            lang = get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
            await ctx.respond(l10n.get('no_permission', lang), ephemeral=True)
    else:
        logging.error(f"Command error: {error}", exc_info=True)

if __name__ == "__main__":
    LOCALES_DIR.mkdir(exist_ok=True)
    bot.run(TOKEN)