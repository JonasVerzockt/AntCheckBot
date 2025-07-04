#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File: bot.py
Author: Jonas Beier
Date: 2025-07-02
Version: 4.5
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
import discord.errors
import sqlite3
import json
import os
import logging
from datetime import datetime, timedelta
import psutil
import platform
from pathlib import Path
from logging.handlers import RotatingFileHandler
from thefuzz import process
from concurrent.futures import ThreadPoolExecutor
import asyncio
import sys
import traceback
import re
# Pfade und Konfiguration
SHOP_DATA = {}
BASE_DIR = Path(__file__).parent
LOCALES_DIR = BASE_DIR / "locales"
TOKEN = "TOKEN"
DATA_DIRECTORY = "DIR"
SHOPS_DATA_FILE = "shops_data.json"
DM_BLOCKED_FILE = BASE_DIR / "dm_blocked_users.json"
SERVER_IDS = [ID1, ID2]
BOT_OWNER = USERID
EU_COUNTRIES_FILE = "eu_countries.json"
EU_COUNTRY_CODES = None
EU_COUNTRY_CODES_LOCK = asyncio.Lock()
db_executor = ThreadPoolExecutor(max_workers=5)
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
# EU Liste laden
async def load_eu_countries():
    rows = await execute_db("SELECT code FROM eu_countries", fetch=True)
    return [row["code"].lower() for row in rows]
# Datenbankverbindung
async def execute_db(query, params=(), commit=False, fetch=False):
    def sync_task():
        conn = sqlite3.connect(BASE_DIR / "antcheckbot.db", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            logging.debug(f"Executing query: {query}, with params: {params}")
            cursor.execute(query, params)
            if commit:
                conn.commit()
                logging.debug("Transaction committed")
            if fetch:
                return cursor.fetchall()
                logging.debug(f"Fetch result: {result}")
            return cursor.rowcount
            logging.debug(f"Rowcount: {result}")
        finally:
            conn.close()
            logging.debug("Connection closed")
    return await bot.loop.run_in_executor(db_executor, sync_task)
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
async def get_user_lang(user_id, server_id):
    if user_id is None:
        logging.error("get_user_lang: user_id is None!")
        return 'en'
    if server_id is None:
        logging.error("get_user_lang: server_id is None!")
        return 'en'
    user_id = int(user_id)
    server_id = int(server_id)
    logging.info(f"get_user_lang called with user_id={user_id}, server_id={server_id}")
    rows_user = await execute_db("SELECT language FROM user_settings WHERE user_id=?", (user_id,), fetch=True)
    logging.info(f"DB result for user_settings: {rows_user}")
    if rows_user:
        user_lang = rows_user[0][0]
        logging.info(f"Returning user language: {user_lang}")
        return user_lang
    rows_server = await execute_db("SELECT language FROM server_settings WHERE server_id=?", (server_id,), fetch=True)
    logging.info(f"DB result for server_settings: {rows_server}")
    if rows_server:
        server_lang = rows_server[0][0]
        logging.info(f"Returning server language: {server_lang}")
        return server_lang
    logging.info("Returning default language: 'en'")
    return 'en'
# Hilfefunktionen und Decorators
def load_dm_blocked_users():
    try:
        with open(DM_BLOCKED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()
def save_dm_blocked_users(blocked_set):
    with open(DM_BLOCKED_FILE, "w", encoding="utf-8") as f:
        json.dump(list(blocked_set), f)
dm_blocked_users = load_dm_blocked_users()
def normalize_species_name(name):
    name = re.sub(r'\s*\b(cf|sp|aff)\.?\s*', ' ', name, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', name).strip().lower()
async def ensure_shop_data():
    global SHOP_DATA
    if SHOP_DATA is None or asyncio.iscoroutine(SHOP_DATA):
        SHOP_DATA = await load_shop_data()
async def get_server_channel(server_id):
    server_id = int(server_id)
    rows = await execute_db("SELECT channel_id FROM server_settings WHERE server_id=?", (server_id,), fetch=True)
    return rows[0][0] if rows else None
async def get_setting(server_id, channel_id):
    server_id = int(server_id)
    channel_id = int(channel_id)
    query = "SELECT channel_id FROM server_settings WHERE server_id=? AND channel_id=?"
    params = (server_id, channel_id)
    result = await execute_db(query, params, fetch=True)
    if result:
        return result[0]['channel_id']
    else:
        return None
def allowed_channel():
    async def predicate(ctx):
        logging.debug(f"Context in allowed_channel: {ctx}")
        if ctx.guild is None:
            return True
        channel_id = await get_setting(ctx.guild.id, ctx.channel.id)
        if channel_id is None:
            return True
        if ctx.channel.id == channel_id:
            return True
        lang = await get_user_lang(ctx.author.id, ctx.guild.id)
        raise commands.CheckFailure(l10n.get('wrong_channel', lang))
    return commands.check(predicate)
def admin_or_manage_messages():
    async def predicate(ctx):
        perms = ctx.author.guild_permissions
        return perms.administrator or perms.manage_messages
    return commands.check(predicate)
async def species_exists(species):
    def sync_task():
        import re
        def normalize_species_name(name):
            name = re.sub(r'\s*\b(cf|sp|aff)\.?\s*', ' ', name, flags=re.IGNORECASE)
            return re.sub(r'\s+', ' ', name).strip().lower()
        normalized_search = normalize_species_name(species)
        is_genus_search = ' ' not in normalized_search
        for filename in os.listdir(DATA_DIRECTORY):
            if filename.startswith("products_shop_") and filename.endswith(".json"):
                file_path = os.path.join(DATA_DIRECTORY, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for product in data:
                            title = product.get("title", "").strip()
                            normalized_title = normalize_species_name(title)
                            if is_genus_search:
                                if normalized_title.startswith(normalized_search + ' '):
                                    return True
                            else:
                                if normalized_title == normalized_search:
                                    return True
                except Exception as e:
                    logging.error(f"Error processing {filename}: {e}")
                    continue
        return False
    return await bot.loop.run_in_executor(None, sync_task)
async def check_availability_for_species(
    species_or_genus,
    regions,
    user_id=None,
    ch_mode=False,
    ch_shops=None,
    excluded_species_list=None
):
    logger = logging.getLogger("availability")
    logger.info(
        f"Start availability check for: '{species_or_genus}', "
        f"regions: {regions}, User: {user_id}, CH-Mode: {ch_mode}, "
        f"Exclude: {excluded_species_list}"
    )
    if user_id is not None:
        blacklisted_shops = await get_blacklisted_shops(user_id)
    else:
        blacklisted_shops = set()
    SHOP_DATA = await load_shop_data()
    if excluded_species_list is None:
        excluded_species_list = set()
    def sync_task(blacklisted_shops, SHOP_DATA, ch_shops, excluded_species_list):
        available_products = []
        search_term_cf = species_or_genus.strip().casefold()
        is_genus_search = " " not in species_or_genus.strip()
        for filename in os.listdir(DATA_DIRECTORY):
            if not (filename.startswith("products_shop_") and filename.endswith(".json")):
                continue
            file_path = os.path.join(DATA_DIRECTORY, filename)
            try:
                shop_id_from_filename = int(filename.split("_")[2].split(".")[0])
            except Exception:
                continue
            shop_id_str = str(shop_id_from_filename)
            if ch_mode:
                if not ch_shops:
                    try:
                        with open("shops_ch_delivery.json", "r", encoding="utf-8") as f:
                            manual = {str(e["shop_id"]) for e in json.load(f)}
                        auto = {
                            sid for sid, sd in SHOP_DATA.items()
                            if sd.get("country", "").lower() == "ch"
                        }
                        ch_shops = manual.union(auto)
                    except Exception as e:
                        logger.error(f"CH mode init failed: {e}")
                        return []
                if shop_id_str not in ch_shops:
                    continue
            else:
                shop_data = SHOP_DATA.get(shop_id_str)
                if not shop_data:
                    continue
                shop_country = shop_data.get("country", "").lower()
                if shop_country not in [r.lower() for r in regions]:
                    continue
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    products = json.load(f)
            except Exception:
                continue
            for product in products:
                if not product.get("in_stock", False):
                    continue
                pid = str(product.get("shop_id"))
                if pid in blacklisted_shops:
                    continue

                title = product.get("title", "").strip()
                normalized_title = normalize_species_name(title)
                normalized_search = normalize_species_name(species_or_genus)
                match = False
                if is_genus_search:
                    if normalized_title.startswith(normalized_search + " "):
                        part = normalized_title.split()[1]
                        if part not in excluded_species_list:
                            match = True
                else:
                    match = normalized_title == normalized_search
                if match:
                    shop_info = SHOP_DATA.get(shop_id_str, {})
                    available_products.append({
                        "id": product.get("id"),
                        "species": title,
                        "shop_name": shop_info.get("name", ""),
                        "min_price": product.get("min_price"),
                        "max_price": product.get("max_price"),
                        "currency_iso": product.get("currency_iso"),
                        "antcheck_url": product.get("antcheck_url"),
                        "shop_url": shop_info.get("url"),
                        "shop_id": shop_id_str
                    })
        logger.info(
            f"Availability check completed for '{species_or_genus}'. "
            f"Found: {len(available_products)}"
        )
        return available_products
    return await bot.loop.run_in_executor(
        None,
        lambda: sync_task(
            blacklisted_shops,
            SHOP_DATA,
            ch_shops or set(),
            excluded_species_list
        )
    )
async def load_shop_data_from_google_sheets():
    def sync_task():
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
            if not values:
                return []
            return values
        except HttpError as err:
            print(f'An error occurred: {err}')
            return []
    return await bot.loop.run_in_executor(None, sync_task)
async def split_message(text, max_length=2000):
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
async def get_blacklisted_shops(user_id):
    user_id = int(user_id)
    rows = await execute_db(
        "SELECT shop_id FROM user_shop_blacklist WHERE user_id=?",
        (user_id,),
        fetch=True
    )
    return {row[0] for row in rows}
async def get_shop_rating(shop_id):
    shop_id = int(shop_id)
    rows = await execute_db(
        "SELECT average_rating FROM shops WHERE id = ?",
        (shop_id,),
        fetch=True
    )
    return rows[0][0] if rows else None
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
def format_rating(rating):
    try:
        rating = float(rating)
        return f"⭐ {rating:.2f}"
    except (TypeError, ValueError):
        return "❌"
def expand_regions(regions):
    global EU_COUNTRY_CODES
    if EU_COUNTRY_CODES is None:
         logging.error("EU_COUNTRY_CODES not loaded before expand_regions call!")
         return regions

    regions = [r.strip().lower() for r in regions]
    if "eu" in regions:
        regions = [r for r in regions if r != "eu"]
        if isinstance(EU_COUNTRY_CODES, (list, set)):
             regions = list(set(regions + list(EU_COUNTRY_CODES)))
        else:
             logging.error(f"EU_COUNTRY_CODES has unexpected type in expand_regions: {type(EU_COUNTRY_CODES)}")
    return regions
async def load_eu_countries_if_needed():
    global EU_COUNTRY_CODES
    async with EU_COUNTRY_CODES_LOCK:
        if not EU_COUNTRY_CODES or asyncio.iscoroutine(EU_COUNTRY_CODES):
            EU_COUNTRY_CODES = await load_eu_countries()
            EU_COUNTRY_CODES = list(EU_COUNTRY_CODES)
            logging.debug(f"EU_COUNTRY_CODES after loading: {type(EU_COUNTRY_CODES)} value: {EU_COUNTRY_CODES}")
def split_availability_messages(entries, max_length=2000):
    chunks = []
    current_chunk = []
    current_length = 0
    for entry in entries:
        entry_length = len(entry) + 2
        if current_length + entry_length > max_length:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = []
            current_length = 0
        current_chunk.append(entry)
        current_length += entry_length
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
    return chunks
async def load_ch_delivery_data():
    def sync_task():
        try:
            with open("shops_ch_delivery.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []
    return await bot.loop.run_in_executor(None, sync_task)
async def save_ch_delivery_data(data):
    def sync_task():
        with open("shops_ch_delivery.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    await bot.loop.run_in_executor(None, sync_task)
async def load_shop_data():
    def load_json():
        with open(SHOPS_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    shops_json = await bot.loop.run_in_executor(None, load_json)
    rows = await execute_db("SELECT id, average_rating FROM shops", fetch=True)
    ratings = {str(row["id"]): row["average_rating"] for row in rows}
    shop_data = {}
    for shop in shops_json:
        shop_id = str(shop["id"])
        shop_data[shop_id] = dict(shop)
        shop_data[shop_id]["average_rating"] = ratings.get(shop_id)
    return shop_data
async def update_server_info(guild):
    data = get_guild_info(guild)
    await execute_db("""
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
    """, data, commit=True)
async def remove_left_servers(bot):
    current_guild_ids = {guild.id for guild in bot.guilds}
    rows = await execute_db("SELECT server_id FROM server_info", fetch=True)
    db_guild_ids = {row[0] for row in rows}
    left_guild_ids = db_guild_ids - current_guild_ids
    for guild_id in left_guild_ids:
        await execute_db("DELETE FROM server_info WHERE server_id = ?", (guild_id,), commit=True)
async def trigger_availability_check(user_id, species, regions, ch_mode=False, excluded_species_list=None):
    global SHOP_DATA
    if excluded_species_list is None:
        excluded_species_list = set()
    try:
        row = await execute_db(
            "SELECT server_id FROM notifications WHERE user_id=? AND species=? AND regions=?",
            (user_id, species, regions), fetch=True
        )
        server_id = row[0]["server_id"] if row and row[0]["server_id"] else None
        lang = await get_user_lang(user_id, server_id)
        ch_shops = []
        if ch_mode:
            try:
                with open("shops_ch_delivery.json", "r", encoding="utf-8") as f:
                    ch_data = json.load(f)
                    ch_shops = [str(entry["shop_id"]) for entry in ch_data]
                    logging.info(f"CH delivery list with {len(ch_shops)} stores loaded for check")
                regions_list = ["ch"]
            except FileNotFoundError:
                logging.error("CH delivery file 'shops_ch_delivery.json' not found")
                return None
            except json.JSONDecodeError:
                logging.error("Invalid JSON format in CH delivery file 'shops_ch_delivery.json'")
                return None
            except Exception as e:
                logging.error(f"Error loading CH data from 'shops_ch_delivery.json': {e}")
                return None
        else:
            regions_list = regions.split(",") if isinstance(regions, str) else regions
            regions_list = expand_regions(regions_list)
        try:
            available = await check_availability_for_species(
                species,
                regions_list,
                user_id=str(user_id),
                ch_mode=ch_mode,
                ch_shops=ch_shops,
                excluded_species_list=excluded_species_list
            )
        except FileNotFoundError as e:
            logging.error(f"Missing product file during availability check: {e.filename}")
            return None
        except Exception as e:
            logging.error(f"Error during availability check function call: {e}", exc_info=True)
            return None
        if not available:
            logging.debug(f"No available products found for {species} in {regions} (excluding: {excluded_species_list})")
            return False
        seen = await execute_db(
            "SELECT product_id FROM user_seen_products WHERE user_id=?",
            (user_id,), fetch=True
        )
        seen_ids = {r["product_id"] for r in seen}
        new_products = [p for p in available if str(p["id"]) not in seen_ids]
        if not new_products:
            return False
        available = new_products
        try:
            user = await bot.fetch_user(int(user_id))
        except Exception as e:
            logging.error(f"Could not fetch user {user_id}: {e}")
            return None
        products_with_ratings = []
        for product in available:
            shop_id = str(product['shop_id'])
            rating = await get_shop_rating(shop_id)
            products_with_ratings.append({"product_data": product, "rating": rating})
        def sort_key(item):
            rating = item["rating"]
            shop_name = item["product_data"].get('shop_name', '').lower()
            return (rating is None, -rating if rating is not None else 0, shop_name)
        sorted_products_with_ratings = sorted(products_with_ratings, key=sort_key)
        header = l10n.get('availability_header', lang, species=species)
        message_entries = [header]
        for item in sorted_products_with_ratings:
            product = item["product_data"]
            rating_str = format_rating(item["rating"])
            shop_id_str = str(product["shop_id"])
            shop_info = SHOP_DATA.get(shop_id_str, {}) if SHOP_DATA and isinstance(SHOP_DATA, dict) else {}
            shop_url = shop_info.get("url", "N/A")
            message_entries.append(l10n.get(
                'availability_entry',
                lang,
                species=product['species'],
                shop=product['shop_name'],
                min_price=product['min_price'],
                max_price=product['max_price'],
                currency=product['currency_iso'],
                product_url=product['antcheck_url'],
                shop_url=shop_url,
                rating=rating_str
            ))
        message_chunks = split_availability_messages(message_entries)
        try:
            for chunk in message_chunks:
                await user.send(chunk)
            for p in new_products:
                await execute_db(
                    "INSERT OR IGNORE INTO user_seen_products (user_id, product_id) VALUES (?, ?)",
                    (user_id, str(p["id"])),
                    commit=True
                )
            current_ids = {str(p["id"]) for p in available}
            to_remove = seen_ids - current_ids
            for pid in to_remove:
                await execute_db(
                    "DELETE FROM user_seen_products WHERE user_id=? AND product_id=?",
                    (user_id, pid),
                    commit=True
                )
            await execute_db("""
                UPDATE notifications
                SET status='completed', notified_at=CURRENT_TIMESTAMP
                WHERE user_id=? AND species=? AND regions=?
            """, (user_id, species, regions), commit=True)
            await ask_for_feedback(user, user_id, species, regions)
            logging.info(f"Successfully sent availability notification to user {user_id} for {species}.")
            return True
        except discord.Forbidden:
            await handle_dm_failure(user_id, species, regions, lang)
            return None
        except Exception as e:
            logging.error(f"Error sending DM to {user_id}: {e}", exc_info=True)
            await execute_db("""
                UPDATE notifications SET status='failed' WHERE user_id=? AND species=? AND regions=?
            """, (user_id, species, regions), commit=True)
            return None
    except Exception as e:
        logging.error(f"Critical error in trigger_availability_check for {user_id}, {species}: {e}", exc_info=True)
        await execute_db("""
            UPDATE notifications SET status='failed' WHERE user_id=? AND species=? AND regions=?
        """, (user_id, species, regions), commit=True)
        return None
async def handle_dm_failure(user_id, species, regions, lang):
    try:
        if isinstance(regions, str):
            regions_list = [r.strip() for r in regions.split(",") if r.strip()]
        else:
            regions_list = regions
        servers = await execute_db("""
            SELECT DISTINCT server_id FROM server_user_mappings
            WHERE user_id=?
        """, (user_id,), fetch=True)

        used_server_ids = set()
        for (server_id,) in servers:
            used_server_ids.add(server_id)
            key = f"{user_id}-{server_id}"
            if key in dm_blocked_users:
                continue
            channel_id = await get_server_channel(server_id)
            channel = bot.get_channel(channel_id) if channel_id else None
            if not channel:
                guild = bot.get_guild(server_id)
                channel = guild.system_channel if guild else None
            if channel:
                try:
                    await channel.send(
                        f"<@{user_id}>, {l10n.get('dm_failed', lang)}\n"
                        f"**Art:** {species}\n"
                        f"**Regions:** {', '.join(regions_list)}"
                    )
                    dm_blocked_users.add(key)
                    save_dm_blocked_users(dm_blocked_users)
                except discord.HTTPException as e:
                    if hasattr(e, "status") and e.status == 429:
                        logging.warning(f"Rate limit in channel {server_id}: {e}")
                        await asyncio.sleep(e.retry_after)
                    else:
                        raise
        if not used_server_ids:
            row = await execute_db(
                "SELECT server_id FROM notifications WHERE user_id=? AND species=? AND regions=?",
                (user_id, species, regions), fetch=True
            )
            if row and row[0]["server_id"]:
                server_id = row[0]["server_id"]
                key = f"{user_id}-{server_id}"
                if key not in dm_blocked_users:
                    channel_id = await get_server_channel(server_id)
                    channel = bot.get_channel(channel_id) if channel_id else None
                    if not channel:
                        guild = bot.get_guild(server_id)
                        channel = guild.system_channel if guild else None
                    if channel:
                        try:
                            await channel.send(
                                f"<@{user_id}>, {l10n.get('dm_failed', lang)}\n"
                                f"**Art:** {species}\n"
                                f"**Regions:** {', '.join(regions_list)}"
                            )
                            dm_blocked_users.add(key)
                            save_dm_blocked_users(dm_blocked_users)
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
async def get_user_data(user_id):
    return {
        "settings": query_to_dict("SELECT * FROM user_settings WHERE user_id=?", user_id),
        "notifications": query_to_dict("SELECT * FROM notifications WHERE user_id=?", user_id),
        "blacklist": query_to_dict("SELECT shop_id FROM user_shop_blacklist WHERE user_id=?", user_id),
        "server_mappings": query_to_dict("SELECT server_id FROM server_user_mappings WHERE user_id=?", user_id)
    }
async def get_owned_servers_data(user):
    owned_servers = []
    for guild in bot.guilds:
        try:
            owner_id = (await bot.fetch_guild(guild.id)).owner_id
            if owner_id == user.id:
                owned_servers.append({
                    "server_info": query_to_dict("SELECT * FROM server_info WHERE server_id=?", guild.id),
                    "server_settings": query_to_dict("SELECT * FROM server_settings WHERE server_id=?", guild.id)
                })
        except discord.NotFound:
            continue
    return owned_servers
async def query_to_dict(query, *params):
    rows = await execute_db(query, params, fetch=True)
    return [dict(row) for row in rows]
async def create_temp_file(data, filename):
    def sync_task():
        json_data = json.dumps(data, indent=2, ensure_ascii=False)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(json_data)
    await bot.loop.run_in_executor(None, sync_task)
    return discord.File(
        filename,
        filename=filename,
        description="Personal data export"
    )
async def reload_shops():
    try:
        with open(SHOPS_DATA_FILE, "r") as f:
            shops = json.load(f)
            SHOP_DATA = {shop["id"]: shop for shop in shops}
            for shop in SHOP_DATA.values():
                await execute_db("""
                    INSERT OR REPLACE INTO shops (id, name, country, url)
                    VALUES (?, ?, ?, ?)
                """, (str(shop["id"]), shop["name"], shop["country"], shop["url"]), commit=True)
    except Exception as e:
        logging.error(f"Error reloading shop data: {e}")
async def get_file_age(filename):
    def sync_task():
        try:
            modified = os.path.getmtime(filename)
            age = datetime.now() - datetime.fromtimestamp(modified)
            days = age.days
            hours, remainder = divmod(age.seconds, 3600)
            minutes = remainder // 60
            return f"{days}d {hours}h {minutes}m", datetime.fromtimestamp(modified).strftime('%Y-%m-%d %H:%M:%S')
        except FileNotFoundError:
            return None, "File not found"
    return await bot.loop.run_in_executor(None, sync_task)
async def ask_for_feedback(user, user_id, species, regions):
    row = await execute_db(
        "SELECT server_id FROM notifications WHERE user_id=? AND species=? AND regions=?",
        (user_id, species, regions), fetch=True
    )
    server_id = row[0]["server_id"] if row and row[0]["server_id"] else None
    lang = await get_user_lang(user_id, server_id)
    question = await user.send(
        l10n.get('feedback_question', lang)
    )
    await question.add_reaction("👍")
    await question.add_reaction("🔄")
    pending_until = datetime.utcnow() + timedelta(hours=48)
    await execute_db(
        "UPDATE notifications SET status='pending_feedback', pending_feedback_until=? "
        "WHERE user_id=? AND species=? AND regions=? AND status='completed'",
        (pending_until.strftime("%Y-%m-%d %H:%M:%S"), user_id, species, regions),
        commit=True
    )
    def check(reaction, reactor):
        return (
            reactor.id == int(user_id)
            and reaction.message.id == question.id
            and str(reaction.emoji) in ["👍", "🔄"]
        )
    try:
        reaction, _ = await bot.wait_for(
            "reaction_add",
            timeout=48*3600,
            check=check
        )
        if str(reaction.emoji) == "👍":
            await execute_db(
                "DELETE FROM user_seen_products WHERE user_id=?",
                (user_id,), commit=True
            )
            await execute_db(
                "UPDATE notifications SET status='completed', pending_feedback_until=NULL "
                "WHERE user_id=? AND species=? AND regions=?",
                (user_id, species, regions), commit=True
            )
            ack = l10n.get('feedback_positive_ack', lang)
            await user.send(ack)
        else:
            await execute_db(
                "UPDATE notifications SET status='active', pending_feedback_until=NULL "
                "WHERE user_id=? AND species=? AND regions=?",
                (user_id, species, regions), commit=True
            )
            ack = l10n.get('feedback_continue_ack', lang)
            await user.send(ack)
    except asyncio.TimeoutError:
        await execute_db(
            "UPDATE notifications SET status='expired', pending_feedback_until=NULL "
            "WHERE user_id=? AND species=? AND regions=?",
            (user_id, species, regions), commit=True
        )
        try:
            timeout_msg = l10n.get(
                'feedback_timeout',
                lang,
                species=species,
                regions=regions
            )
            await user.send(timeout_msg)
        except:
            pass
# Befehle
@bot.slash_command(name="startup",description="Set the server language and where the bot should respond (only Admin/Mod)")
@admin_or_manage_messages()
async def setup_server(ctx, language: discord.Option(str, "Select the bot language (de = German, en = English, eo = Esperanto)", choices=["de", "en", "eo"], default="en"), channel: discord.Option(discord.TextChannel, "Channel for bot responses (optional)", required=False) = None):
    server_id = ctx.guild.id
    channel_id = channel.id if channel else None
    if channel_id is not None:
        await execute_db("""
            INSERT INTO server_settings (server_id, channel_id, language)
            VALUES (?, ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                channel_id=excluded.channel_id,
                language=excluded.language
        """, (server_id, channel_id, language), commit=True)
    else:
        await execute_db("""
            INSERT INTO server_settings (server_id, language)
            VALUES (?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                language=excluded.language
        """, (server_id, language), commit=True)
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
    await execute_db("""
    INSERT INTO user_settings (user_id, language)
    VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET language=excluded.language
    """, (user_id, language), commit=True)
    await ctx.respond(l10n.get('user_setting_success', language), ephemeral=True)
@user_settings.command(description="Add shop to blacklist")
@allowed_channel()
async def blacklist_add(ctx, shop: discord.Option(str, "Shop name or ID", required=True)):
    await ensure_shop_data()
    user_id = str(ctx.author.id)
    lang = await get_user_lang(user_id, ctx.guild.id if ctx.guild else None)
    shop_names = {s_id: s_data["name"] for s_id, s_data in SHOP_DATA.items()}
    matches = process.extract(shop, shop_names.values(), limit=3)
    best_match = next((match for match in matches if match[1] > 75), None)
    if not best_match:
        suggestions = "\n".join([f"- {m[0]}" for m in matches])
        await ctx.respond(
            l10n.get('shop_not_found_suggest', lang, shop=shop, suggestions=suggestions),
            ephemeral=True
        )
        return
    shop_name = best_match[0]
    shop_id = str(next(s_id for s_id, name in shop_names.items() if name == shop_name))
    await execute_db(
        """
        INSERT INTO user_shop_blacklist (user_id, shop_id)
        VALUES (?, ?)
        ON CONFLICT(user_id, shop_id) DO NOTHING
        """,
        (user_id, shop_id),
        commit=True
    )
    await ctx.respond(
        l10n.get('blacklist_add_success', lang, shop=shop_name),
        ephemeral=True
    )
@user_settings.command(description="Remove shop from blacklist")
@allowed_channel()
async def blacklist_remove(ctx, shop: discord.Option(str, "Shop name or ID", required=True)):
    await ensure_shop_data()
    user_id = str(ctx.author.id)
    lang = await get_user_lang(user_id, ctx.guild.id if ctx.guild else None)
    shop_names = {s_id: s_data["name"] for s_id, s_data in SHOP_DATA.items()}
    matches = process.extract(shop, shop_names.values(), limit=3)
    best_match = next((match for match in matches if match[1] > 75), None)
    if not best_match:
        suggestions = "\n".join([f"- {m[0]}" for m in matches])
        await ctx.respond(
            l10n.get('shop_not_found_suggest', lang, shop=shop, suggestions=suggestions),
            ephemeral=True
        )
        return
    shop_name = best_match[0]
    shop_id = str(next(s_id for s_id, name in shop_names.items() if name == shop_name))
    rowcount = await execute_db(
        """
        DELETE FROM user_shop_blacklist
        WHERE user_id=? AND shop_id=?
        """,
        (user_id, shop_id),
        commit=True
    )
    if rowcount > 0:
        await ctx.respond(
            l10n.get('blacklist_remove_success', lang, shop=shop_name),
            ephemeral=True
        )
    else:
        await ctx.respond(l10n.get('shop_not_in_blacklist', lang), ephemeral=True)
@user_settings.command(description="List blacklisted shops")
@allowed_channel()
async def blacklist_list(ctx):
    await ensure_shop_data()
    user_id = str(ctx.author.id)
    lang = await get_user_lang(user_id, ctx.guild.id if ctx.guild else None)
    rows = await execute_db(
        "SELECT shop_id FROM user_shop_blacklist WHERE user_id=?",
        (user_id,),
        fetch=True
    )
    shops = [SHOP_DATA[str(row["shop_id"])]["name"] for row in rows if str(row["shop_id"]) in SHOP_DATA]
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
    country: discord.Option(str, "Filter shops by region code (e.g., de, at) or 'ch' for Swiss delivery", required=False) = None):
    lang = await get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
    await ensure_shop_data()
    global SHOP_DATA
    pre_filtered_shops = []
    if country:
        country_lower = country.lower()
        if country_lower == "ch":
            try:
                ch_data = await load_ch_delivery_data()
                manual_ch_shop_ids = {str(entry["shop_id"]) for entry in ch_data}
                logging.debug(f"CH Filter: Found {len(manual_ch_shop_ids)} shops in ch_delivery.json")
                auto_ch_shop_ids = {
                    str(shop_id) for shop_id, shop_data in SHOP_DATA.items()
                    if shop_data.get("country", "").lower() == "ch"
                }
                logging.debug(f"CH Filter: Found {len(auto_ch_shop_ids)} shops with country 'ch' in SHOP_DATA")
                combined_ch_shop_ids = manual_ch_shop_ids.union(auto_ch_shop_ids)
                logging.debug(f"CH Filter: Total unique CH shops to list: {len(combined_ch_shop_ids)}")
                pre_filtered_shops = [v for k, v in SHOP_DATA.items() if str(k) in combined_ch_shop_ids]
                logging.debug(f"CH Filter: Final filtered list size: {len(pre_filtered_shops)}")
            except Exception as e:
                logging.error(f"Error during CH filter processing in shop_list: {e}")
                await ctx.respond(l10n.get('general_error', lang), ephemeral=True)
                return
        else:
            pre_filtered_shops = [
                s for s in SHOP_DATA.values()
                if s.get("country", "").lower() == country_lower
            ]
            logging.debug(f"Country Filter '{country_lower}': Found {len(pre_filtered_shops)} shops")
    else:
        pre_filtered_shops = list(SHOP_DATA.values())
        logging.debug(f"No Filter: Using all {len(pre_filtered_shops)} shops")
    if not pre_filtered_shops:
        await ctx.respond(l10n.get('no_shops_found', lang), ephemeral=True)
        return
    shops_with_live_ratings = []
    for shop_dict in pre_filtered_shops:
        shop_id = str(shop_dict.get('id'))
        if not shop_id:
            logging.warning(f"Shop dictionary missing 'id': {shop_dict.get('name', 'N/A')}")
            continue
        try:
            live_rating = await get_shop_rating(shop_id)
            shops_with_live_ratings.append({
                **shop_dict,
                'live_rating': live_rating
            })
        except Exception as e:
            logging.error(f"Error fetching rating for shop {shop_id} in shop_list: {e}")
            shops_with_live_ratings.append({**shop_dict, 'live_rating': None})
    def sort_key_with_live_rating(shop_info):
        rating = shop_info.get('live_rating')
        shop_name = shop_info.get('name', '').lower()
        rating_value = None
        try:
            if rating is not None:
                rating_value = float(rating)
        except (ValueError, TypeError):
            rating_value = None

        return (
            rating_value is None,
            -rating_value if rating_value is not None else 0,
            shop_name
        )
    shops_sorted = sorted(shops_with_live_ratings, key=sort_key_with_live_rating)
    shop_entries = []
    for s in shops_sorted:
        shop_id = s.get('id', 'N/A')
        shop_name = s.get('name', 'Unknown Name')
        rating_str = format_rating(s.get('live_rating'))
        shop_entry = f"`{shop_id}` | {shop_name} - {rating_str}"
        shop_entries.append(shop_entry)
    if not shop_entries:
         await ctx.respond(l10n.get('no_shops_found', lang), ephemeral=True)
         return
    text = l10n.get('available_shops', lang, shops="\n- " + "\n- ".join(shop_entries))
    blocks = await split_message(text)
    try:
        await ctx.respond(blocks[0], ephemeral=True)
        for block in blocks[1:]:
            await ctx.followup.send(block, ephemeral=True)
    except IndexError:
        logging.error("split_message returned an empty list unexpectedly for shop_list.")
        await ctx.respond(l10n.get('general_error', lang), ephemeral=True)
    except discord.HTTPException as e:
         logging.error(f"Error sending shop list response (HTTPException): {e}")
         try:
             await ctx.followup.send(l10n.get('general_error', lang), ephemeral=True)
         except Exception:
             logging.error("Failed to send error followup message.")
@bot.slash_command(name="notification", description="Set up notifications for a specific species or an entire genus")
@allowed_channel()
async def notification(
    ctx,
    species: discord.Option(str, "Specific species (e.g., Messor barbarus)", required=False, default=None),
    genus: discord.Option(str, "Genus (e.g., Messor) - notifies for ALL species in this genus", required=False, default=None),
    exclude_species: discord.Option(str, "Comma-separated species to exclude (only used with 'genus')", required=False, default=None),
    regions: discord.Option(str, "Regions (comma-separated, e.g., de,at,eu or 'ch' if swiss_only=True)", required=False, default=None),
    swiss_only: discord.Option(bool, "Only CH-delivering stores (overrides regions)", default=False),
    force: discord.Option(bool, "Force notification even if already active", default=False)
):
    server_id = ctx.guild.id if ctx.guild else None
    lang = await get_user_lang(ctx.author.id, server_id)
    global SHOP_DATA
    SHOP_DATA = await load_shop_data()
    if species and genus:
        await ctx.respond(l10n.get('notification_error_both_genus_species', lang), ephemeral=True)
        return
    if not species and not genus:
        await ctx.respond(l10n.get('notification_error_neither_genus_species', lang), ephemeral=True)
        return
    if species is not None and " " not in species:
        await ctx.respond(l10n.get('notification_error_species_format', lang, species=species), ephemeral=True)
        return
    search_term = species if species else genus
    search_type = "species" if species else "genus"
    excluded_species_str = None
    if search_type == "genus" and exclude_species:
        excluded_species_str = exclude_species.strip().lower()
        if not excluded_species_str:
             excluded_species_str = None
    logging.info(f"Notification request: User={ctx.author.id}, Term='{search_term}' (Type: {search_type}), Exclude='{excluded_species_str}', Regions='{regions}', CH={swiss_only}, Force={force}")
    valid_regions = []
    ch_shops = None
    if swiss_only:
        try:
            ch_data = await load_ch_delivery_data()
            ch_shops = {str(entry["shop_id"]) for entry in ch_data}
            auto_ch_shops = {str(s_id) for s_id, s_data in SHOP_DATA.items() if s_data.get("country", "").lower() == "ch"}
            ch_shops.update(auto_ch_shops)
            regions_list = ["ch"]
            valid_regions = ["ch"]
            logging.debug(f"Swiss-only mode. Using CH regions. Found {len(ch_shops)} shops.")
        except Exception as e:
            logging.error(f"Error loading CH data for swiss_only mode: {e}")
            await ctx.respond(l10n.get('ch_notification_error', lang), ephemeral=True)
            return
    else:
        if not regions:
            available_regions = sorted({s.get("country", "").lower() for s_id, s in SHOP_DATA.items() if s.get("country")})
            available_regions_str = ", ".join(available_regions)
            await ctx.respond(l10n.get('notification_error_no_region', lang, regions=available_regions_str), ephemeral=True)
            return
        regions_list = [r.strip().lower() for r in regions.split(",")] if regions else []
        await load_eu_countries_if_needed()
        expanded_regions_list = expand_regions(regions_list)
        available_shop_countries = {s.get("country", "").lower() for s_id, s in SHOP_DATA.items() if s.get("country")}
        valid_regions = [r for r in expanded_regions_list if r in available_shop_countries]
        if not valid_regions:
            available_regions_str = ", ".join(sorted(available_shop_countries))
            await ctx.respond(l10n.get('invalid_regions', lang, regions=available_regions_str), ephemeral=True)
            return
        logging.debug(f"Validated regions for notification: {valid_regions}")
    term_exists = await species_exists(search_term)
    if term_exists or force:
        try:
            regions_str = ",".join(valid_regions)
            user_id_str = str(ctx.author.id)
            server_id = ctx.guild.id if ctx.guild else None
            existing_active = await execute_db("""
                SELECT 1 FROM notifications
                WHERE user_id = ? AND species = ? AND regions = ? AND status = 'active'
            """, (user_id_str, search_term, regions_str), fetch=True)
            if existing_active and not force:
                 await ctx.respond(l10n.get('notification_exists_active', lang, species=search_term, regions=regions_str))
                 return
            rowcount = await execute_db("""
                INSERT INTO notifications (user_id, species, regions, status, excluded_species, server_id)
                VALUES (?, ?, ?, 'active', ?, ?)
                ON CONFLICT(user_id, species, regions)
                DO UPDATE SET created_at=CURRENT_TIMESTAMP, status='active', excluded_species=excluded.excluded_species, server_id = excluded.server_id
            """, (user_id_str, search_term, regions_str, excluded_species_str, server_id), commit=True)
            logging.debug(f"DB operation rowcount: {rowcount} for user {user_id_str}, term '{search_term}', regions '{regions_str}', exclude '{excluded_species_str}'")
            response_key = 'notification_set'
            if force and not existing_active:
                 response_key = 'notification_set_forced'
            elif not existing_active:
                 previous_inactive = await execute_db("""
                     SELECT 1 FROM notifications
                     WHERE user_id = ? AND species = ? AND regions = ? AND status != 'active'
                 """, (user_id_str, search_term, regions_str), fetch=True)
                 if previous_inactive:
                     response_key = 'notification_reactivated'
            elif force and existing_active:
                 response_key = 'notification_reactivated'
            log_message = f"Notification for '{search_term}' (User: {user_id_str}) "
            if response_key == 'notification_reactivated': log_message += "reactivated/force-updated."
            elif response_key == 'notification_set_forced': log_message += "set (forced)."
            elif response_key == 'notification_set': log_message += "set."
            if excluded_species_str:
                 log_message += f" Excluding: '{excluded_species_str}'"
            logging.info(log_message)
            response_params = {'species': search_term, 'regions': regions_str}
            if excluded_species_str:
                 response_params['excluded'] = excluded_species_str
                 response_key += "_with_exclude"
            await ctx.respond(l10n.get(response_key, lang, **response_params))
            if server_id:
                await execute_db("""
                    INSERT OR IGNORE INTO server_user_mappings (user_id, server_id)
                    VALUES (?, ?)
                """, (user_id_str, server_id), commit=True)
            await ctx.followup.send(l10n.get('checking_availability', lang, species=search_term))
            immediate_excluded_list = set()
            if search_type == "genus" and excluded_species_str:
                 immediate_excluded_list = {s.strip().lower() for s in excluded_species_str.split(',') if s.strip()}
            check_successful = await trigger_availability_check(
                user_id_str,
                search_term,
                regions_str,
                ch_mode=swiss_only,
                excluded_species_list=immediate_excluded_list
            )
            if check_successful is True:
                final_status_message = l10n.get('availability_check_success', lang, species=search_term)
                await ctx.followup.send(final_status_message)
            elif check_successful is False:
                final_status_message = l10n.get('availability_check_not_found', lang, species=search_term)
                await ctx.followup.send(final_status_message)
            else:
                final_status_message = l10n.get('availability_check_error', lang, species=search_term)
                await ctx.followup.send(final_status_message)
        except sqlite3.Error as db_err:
             logging.error(f"Database error during notification setup for '{search_term}' (likely duplicate active): {db_err}", exc_info=True)
             await ctx.followup.send(l10n.get('notification_exists_active', lang, species=search_term, regions=regions_str))
        except Exception as e:
            logging.error(f"Unexpected error setting notification for '{search_term}': {e}", exc_info=True)
            await ctx.followup.send(l10n.get('general_error', lang))
    else:
        await ctx.respond(l10n.get('species_or_genus_not_found', lang, term=search_term), ephemeral=True)
@bot.slash_command(name="delete_notifications", description="Delete your notifications")
@allowed_channel()
async def delete_notifications(ctx, ids: discord.Option(str, "Enter the IDs of the notifications to delete (comma-separated)")):
    lang = await get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
    id_list = [int(i.strip()) for i in ids.split(",") if i.strip().isdigit()]
    if not id_list:
        await ctx.respond(l10n.get('invalid_ids', lang), ephemeral=True)
        return
    rows = await execute_db(
        f"SELECT id FROM notifications WHERE user_id=? AND id IN ({','.join(['?']*len(id_list))})",
        (str(ctx.author.id), *id_list),
        fetch=True
    )
    user_ids = [row["id"] for row in rows]
    if not user_ids:
        await ctx.respond(l10n.get('no_permission', lang), ephemeral=True)
        return
    await execute_db(
        f"DELETE FROM notifications WHERE user_id=? AND id IN ({','.join(['?']*len(user_ids))})",
        (str(ctx.author.id), *user_ids),
        commit=True
    )
    await execute_db(
        "UPDATE global_stats SET value = value + ? WHERE key = 'deleted_notifications'",
        (len(user_ids),),
        commit=True
    )
    await ctx.respond(l10n.get('deleted_success', lang, ids=", ".join(map(str, user_ids))))
@bot.slash_command(name="stats", description="Show relevant statistics (only Admin/Mod)")
@allowed_channel()
@admin_or_manage_messages()
async def stats(ctx):
    lang = await get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
    active = (await execute_db(
        "SELECT COALESCE(COUNT(*), 0) as cnt FROM notifications WHERE status='active'",
        fetch=True
    ))[0]["cnt"]
    completed = (await execute_db(
        "SELECT COALESCE(COUNT(*), 0) as cnt FROM notifications WHERE status='completed'",
        fetch=True
    ))[0]["cnt"]
    expired = (await execute_db(
        "SELECT COALESCE(COUNT(*), 0) as cnt FROM notifications WHERE status='expired'",
        fetch=True
    ))[0]["cnt"]
    top_species = await execute_db(
        """
        SELECT COALESCE(species, 'unknown') as species, COUNT(*) as cnt
        FROM notifications
        GROUP BY species
        ORDER BY cnt DESC
        LIMIT 5
        """,
        fetch=True
    )
    deleted_total = (await execute_db(
        "SELECT COALESCE(value, 0) as val FROM global_stats WHERE key = 'deleted_notifications'",
        fetch=True
    ))[0]["val"]
    stats_msg = l10n.get(
        'stats_message',
        lang,
        active=active,
        completed=completed,
        expired=expired,
        deleted_total=deleted_total,
        top_species="\n".join([f"- {s['species']}: {s['cnt']}" for s in top_species])
    )
    await ctx.respond(stats_msg)
@bot.slash_command(name="history", description="Show your requests")
@allowed_channel()
async def history(ctx):
    server_id = ctx.guild.id if ctx.guild else None
    lang = await get_user_lang(ctx.author.id, server_id)
    try:
        history = await execute_db(
            "SELECT id, species, regions, status, created_at, notified_at FROM notifications WHERE user_id=? ORDER BY created_at DESC",
            (str(ctx.author.id),),
            fetch=True
        )
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
    lang = await get_user_lang(ctx.author.id, server_id)
    server_count = len(bot.guilds)
    user_count = sum(guild.member_count for guild in bot.guilds)
    try:
        uptime = datetime.now() - bot.start_time
        total = (await execute_db("SELECT COUNT(*) FROM notifications", fetch=True))[0][0]
        integrity = (await execute_db("PRAGMA integrity_check", fetch=True))[0][0]
        age, modified = await get_file_age(SHOPS_DATA_FILE)
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
    lang = await get_user_lang(ctx.author.id, server_id)
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
            l10n.get('help_showservers', lang),
            l10n.get('help_export', lang),
            l10n.get('help_ch_mapping', lang)
        ])
        await ctx.respond(l10n.get('help_full', lang, commands=commands))
    except Exception as e:
        logging.error(f"Help error: {e}")
        await ctx.respond(l10n.get('general_error', lang))
@bot.slash_command(name="testnotification", description="Test PN notifications")
@allowed_channel()
async def testnotification(ctx):
    server_id = ctx.guild.id if ctx.guild else None
    lang = await get_user_lang(ctx.author.id, server_id)
    try:
        await ctx.author.send(l10n.get('testnotification_dm', lang))
        await ctx.respond(l10n.get('testnotification_success', lang), ephemeral=True)
    except discord.Forbidden:
        await ctx.respond(l10n.get('testnotification_forbidden', lang), ephemeral=True)
@bot.slash_command(name="reloadshops", description="Reload shop data from JSON file (only Admin/Mod)")
@admin_or_manage_messages()
@allowed_channel()
async def reloadshops(ctx):
    await sync_ratings()
    global SHOP_DATA
    SHOP_DATA = await load_shop_data()
    await ctx.respond("Store data has been reloaded.")
shopmapping = bot.create_group(
    name="shopmapping",
    description="Manage shop name mappings for Google Sheets imports! (only for AAM-Discord)",
    guild_ids=SERVER_IDS
)
@shopmapping.command(name="add", description="Assign external shop name to internal ID (only for AAM-Discord)")
@admin_or_manage_messages()
@allowed_channel()
async def shopmapping_add(
    ctx,
    external_name: discord.Option(str, "Name from Google Sheets"),
    shop_id: discord.Option(str, "Internal shop ID")
):
    await ensure_shop_data()
    lang = await get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
    shop_id = str(shop_id)
    if shop_id not in SHOP_DATA:
        await ctx.respond(l10n.get("shopmapping_add_invalid_id", lang), ephemeral=True)
        return
    try:
        await execute_db("""
            INSERT INTO shop_name_mappings (external_name, shop_id)
            VALUES (?, ?)
            ON CONFLICT(external_name) DO UPDATE SET shop_id=excluded.shop_id
        """, (external_name.strip(), shop_id), commit=True)
        await ctx.respond(
            l10n.get("shopmapping_add_success", lang, external=external_name, id=shop_id, shop=SHOP_DATA[shop_id]['name']))
    except Exception as e:
        logging.error(f"Shopmapping add error: {e}")
        await ctx.respond(l10n.get("shopmapping_add_error", lang), ephemeral=True)
@shopmapping.command(name="show", description="Show all current mappings (only for AAM-Discord)")
@admin_or_manage_messages()
@allowed_channel()
async def shopmapping_show(ctx):
    await ensure_shop_data()
    lang = await get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
    mappings = await execute_db("SELECT * FROM shop_name_mappings", fetch=True)
    if not mappings:
        await ctx.respond(l10n.get("shopmapping_show_none", lang))
        return
    msg = [l10n.get("shopmapping_show_header", lang)]
    for row in mappings:
        ext_name = row["external_name"]
        shop_id = row["shop_id"]
        shop_name = SHOP_DATA.get(shop_id, {}).get('name', 'Unknown')
        msg.append(l10n.get("shopmapping_show_entry", lang, external=ext_name, id=shop_id, shop=shop_name))
    await ctx.respond("\n".join(msg))
@shopmapping.command(name="remove", description="Remove a shop mapping (only for AAM-Discord)")
@admin_or_manage_messages()
@allowed_channel()
async def shopmapping_remove(
    ctx,
    external_name: discord.Option(str, "Name from Google Sheets")
):
    lang = await get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
    rowcount = await execute_db("DELETE FROM shop_name_mappings WHERE external_name=?", (external_name,), commit=True)
    if rowcount > 0:
        await ctx.respond(l10n.get("shopmapping_remove_success", lang, external=external_name))
    else:
        await ctx.respond(l10n.get("shopmapping_remove_none", lang))
@bot.slash_command(name="serverlist", description="Shows all server information (only for bot owners)")
@owner_only()
@allowed_channel()
async def serverlist(ctx):
    if ctx.author.id != BOT_OWNER:
        lang = await get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
        await ctx.respond(l10n.get('no_permission', lang), ephemeral=True)
        return
    lang = await get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
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
    for block in await split_message("\n".join(messages)):
        await ctx.respond(block, ephemeral=True)
@bot.slash_command(name="export_data", description="Export all your saved data as JSON")
@allowed_channel()
async def export_data(ctx):
    user_id = str(ctx.author.id)
    lang = await get_user_lang(user_id, ctx.guild.id if ctx.guild else None)
    try:
        owned_servers = await get_owned_servers_data(ctx.author)
        user_data = {
            "user_info": await get_user_data(user_id),
            "servers": owned_servers
        }
        user_file = await create_temp_file(user_data["user_info"], f"user_{user_id}.json")
        files = [user_file]
        if owned_servers:
            server_file = await create_temp_file(owned_servers, f"servers_{user_id}.json")
            files.append(server_file)
            logging.debug(f"Server export for {user_id} with {len(owned_servers)} servers")
        await ctx.author.send(
            l10n.get('data_export_success', lang),
            files=files
        )
        await ctx.respond(l10n.get('data_export_dm_sent', lang), ephemeral=True)
    except Exception as e:
        logging.error(f"Export error: {e}")
        await ctx.respond(l10n.get('data_export_error', lang), ephemeral=True)
    finally:
        for f in files:
            if os.path.exists(f.filename):
                os.remove(f.filename)
ch_delivery = bot.create_group(
    name="ch_delivery",
    description="Management of stores that deliver to Switzerland (only for AAM-Discord)",
    guild_ids=SERVER_IDS
)
@ch_delivery.command(description="Add store to CH delivery list (only for AAM-Discord)")
@allowed_channel()
async def add(ctx, shop_id: discord.Option(str, "Shop-ID")):
    await ensure_shop_data()
    user_id = str(ctx.author.id)
    lang = await get_user_lang(user_id, ctx.guild.id if ctx.guild else None)
    current_data = await load_ch_delivery_data()
    shop_id = str(shop_id)
    if shop_id not in SHOP_DATA:
        await ctx.respond(l10n.get('shop_not_found', lang), ephemeral=True)
        return
    if any(str(entry["shop_id"]) == shop_id for entry in current_data):
        await ctx.respond(
            l10n.get('ch_delivery_exists', lang, shop=SHOP_DATA[shop_id]['name']))
        return
    new_entry = {
        "shop_id": shop_id,
        "added_by": user_id,
        "added_at": datetime.now().isoformat()
    }
    current_data.append(new_entry)
    await save_ch_delivery_data(current_data)
    await ctx.respond(
        l10n.get('ch_delivery_add_success', lang,
                shop=SHOP_DATA[shop_id]['name']))
@ch_delivery.command(description="Remove store from CH delivery list (only for AAM-Discord and Admin/Mod)")
@admin_or_manage_messages()
@allowed_channel()
async def remove(ctx, shop_id: discord.Option(str, "Shop-ID")):
    await ensure_shop_data()
    lang = await get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
    current_data = await load_ch_delivery_data()
    initial_count = len(current_data)
    new_data = [entry for entry in current_data if entry["shop_id"] != shop_id]
    if len(new_data) == initial_count:
        await ctx.respond(
            l10n.get('ch_delivery_not_found', lang),
            ephemeral=True
        )
        return
    await save_ch_delivery_data(new_data)
    await ctx.respond(
        l10n.get('ch_delivery_remove_success', lang,
                shop=SHOP_DATA.get(shop_id, {}).get('name', shop_id)))
@ch_delivery.command(description="Show list of all CH suppliers (only for AAM-Discord)")
@allowed_channel()
async def show(ctx):
    await ensure_shop_data()
    lang = await get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
    current_data = await load_ch_delivery_data()
    if not current_data:
        await ctx.respond(l10n.get('ch_delivery_empty', lang))
        return
    entries = []
    for entry in current_data:
        shop = SHOP_DATA.get(entry["shop_id"], {})
        user = await bot.fetch_user(int(entry["added_by"]))
        timestamp = datetime.fromisoformat(entry["added_at"]).strftime("%d.%m.%Y %H:%M")
        entries.append(
            l10n.get('ch_delivery_entry', lang,
                    shop=shop.get('name', 'Unbekannt'),
                    user=user.display_name,
                    timestamp=timestamp)
        )
    message = l10n.get('ch_delivery_header', lang) + "\n\n" + "\n".join(entries)
    await ctx.respond(message[:2000])
@bot.slash_command(name="reset_failed", description="Reactivates failed notifications after successful PN test")
@allowed_channel()
async def reset_failed(ctx):
    user_id = str(ctx.author.id)
    lang = await get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
    try:
        await ctx.author.send(l10n.get('testnotification_dm', lang))
    except discord.Forbidden:
        await ctx.respond(l10n.get('testnotification_forbidden', lang))
        return
    rowcount = await execute_db(
        "UPDATE notifications SET status='active' WHERE user_id=? AND status='failed'",
        (user_id,),
        commit=True
    )
    key_prefix = f"{user_id}-"
    to_remove = [key for key in dm_blocked_users if key.startswith(key_prefix)]
    for key in to_remove:
        dm_blocked_users.remove(key)
    save_dm_blocked_users(dm_blocked_users)
    await ctx.respond(
        l10n.get('reset_failed_success', lang, count=rowcount),
    )
# Automatisierte Aufgaben
@tasks.loop(hours=168)
async def optimize_db():
    try:
        await execute_db("VACUUM;", commit=True)
        await execute_db("PRAGMA optimize;", commit=True)
        logging.debug("VACUUM and OPTIMIZE completed successfully.")
    except Exception as e:
        logging.error(f"VACUUM/OPTIMIZE error: {e}")
@tasks.loop(hours=24)
async def clean_old_notifications():
    try:
        cutoff = datetime.now() - timedelta(days=365)
        expired = await execute_db("""
            SELECT id, user_id, species, regions
            FROM notifications
            WHERE created_at < ? AND status='active'
        """, (cutoff.strftime('%Y-%m-%d'),), fetch=True)
        await execute_db("""
            UPDATE notifications SET status='expired'
            WHERE created_at < ? AND status='active'
        """, (cutoff.strftime('%Y-%m-%d'),), commit=True)
        for row in expired:
            notif_id, user_id, species, regions = row["id"], row["user_id"], row["species"], row["regions"]
            lang = await get_user_lang(user_id, None)
            await notify_expired(user_id, species, regions, lang)
        logging.debug(f"Old notifications cleaned up and users notified")
    except Exception as e:
        logging.error(f"Error during cleanup: {e}")
@tasks.loop(hours=6)
async def update_server_infos():
    for guild in bot.guilds:
        await update_server_info(guild)
    await remove_left_servers(bot)
@tasks.loop(hours=2)
async def sync_ratings():
    global SHOP_DATA
    logging.debug("Starting combined task: Reloading shops and syncing ratings...")
    try:
        await reload_shops()
        logging.debug("Shop base data reloaded successfully from JSON.")
        await ensure_shop_data()
        raw_data = await load_shop_data_from_google_sheets()
        if not raw_data:
             logging.warning("No data received from Google Sheets for rating sync.")
        all_mappings = await execute_db("SELECT external_name, shop_id FROM shop_name_mappings", fetch=True)
        mapping_dict = {row["external_name"].casefold(): row["shop_id"] for row in all_mappings}
        temp_shop_data_for_matching = SHOP_DATA if SHOP_DATA else await load_shop_data()
        shop_names_for_fuzzy = {s["name"]: k for k, s in temp_shop_data_for_matching.items()}
        updates_made = 0
        for row in raw_data:
            if len(row) < 3:
                logging.warning(f"Skipping incomplete row from Google Sheets: {row}")
                continue
            shop_name, _, rating_str = row
            shop_id = None
            shop_id = mapping_dict.get(shop_name.casefold())
            if not shop_id:
                match = process.extractOne(
                    shop_name,
                    shop_names_for_fuzzy.keys(),
                    scorer=process.fuzz.token_sort_ratio,
                    score_cutoff=75
                )
                if match:
                    matched_name, score = match
                    shop_id = shop_names_for_fuzzy[matched_name]
                    logging.debug(f"Fuzzy matched '{shop_name}' to '{matched_name}' (ID: {shop_id}) with score {score}")
                else:
                    logging.debug(f"Could not map or fuzzy match shop name: '{shop_name}' from Google Sheets.")
                    continue
            if shop_id:
                try:
                    rating_float = float(rating_str.replace(',', '.'))
                    await execute_db("""
                        UPDATE shops
                        SET average_rating = ?
                        WHERE id = ?
                    """, (rating_float, shop_id), commit=True)
                    updates_made += 1
                except (ValueError, TypeError) as ve:
                     logging.warning(f"Invalid rating format for shop '{shop_name}' (ID: {shop_id}): '{rating_str}'. Skipping update. Error: {ve}")
                except Exception as db_err:
                     logging.error(f"Database error updating rating for shop {shop_id}: {db_err}")
        logging.debug(f"Rating sync finished. Updated ratings for {updates_made} shops.")
        SHOP_DATA = await load_shop_data()
        logging.debug("SHOP_DATA cache reloaded successfully after combined task.")
    except Exception as e:
        logging.error(f"Error during combined shop reload and rating sync task: {e}", exc_info=True)
@tasks.loop(hours=1)
async def shop_data_loader():
    global SHOP_DATA
    try:
        SHOP_DATA = await load_shop_data()
        logging.info("Shop data reloaded successfully.")
    except Exception as e:
        logging.error(f"Error reloading shop data: {e}")
        SHOP_DATA = {}
@tasks.loop(minutes=10)
async def expire_pending_feedbacks():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    rows = await execute_db(
        "SELECT id, user_id, species, regions FROM notifications "
        "WHERE status='pending_feedback' AND pending_feedback_until < ?",
        (now,), fetch=True
    )
    for row in rows:
        await execute_db(
            "UPDATE notifications SET status='expired', pending_feedback_until=NULL WHERE id=?",
            (row["id"],), commit=True
        )
        try:
            user = await bot.fetch_user(int(row["user_id"]))
            lang = await get_user_lang(row["user_id"], None)
            msg = l10n.get(
                'notification_expired_dm',
                lang,
                species=row["species"],
                regions=row["regions"]
            )
            await user.send(msg)
        except:
            pass
@tasks.loop(minutes=5)
async def check_availability():
    rows = await execute_db(
        "SELECT user_id, species, regions, excluded_species FROM notifications WHERE status='active'",
        fetch=True
    )
    for row in rows:
        user_id, species_or_genus, regions, excluded_species_str = row["user_id"], row["species"], row["regions"], row["excluded_species"]
        is_genus_notification = " " not in species_or_genus.strip()
        excluded_list = set()
        if is_genus_notification and excluded_species_str:
            excluded_list = {s.strip().lower() for s in excluded_species_str.split(',') if s.strip()}
        ch_mode = regions == "ch"
        await trigger_availability_check(
            user_id,
            species_or_genus,
            regions,
            ch_mode=ch_mode,
            excluded_species_list=excluded_list
        )
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
async def on_application_command_error(ctx, error):
    try:
        lang = await get_user_lang(ctx.author.id, ctx.guild.id if ctx.guild else None)
    except Exception as e:
        logging.error(f"Fehler beim Ermitteln der Sprache im Error Handler: {e}")
        lang = 'en'
    if isinstance(error, commands.CheckFailure) or isinstance(error, discord.errors.CheckFailure):
        wrong_channel_msg = l10n.get('wrong_channel', lang)
        if str(error) == wrong_channel_msg:
            logging.debug(f"CheckFailure erkannt: Falscher Kanal. Meldung: '{str(error)}'")
            try:
                await ctx.respond(wrong_channel_msg)
            except Exception as e:
                 logging.error(f"Fehler beim Senden der 'wrong_channel'-Antwort: {e}")
        else:
            logging.debug(f"CheckFailure erkannt: Keine Berechtigungen oder anderer Check. Meldung: '{str(error)}'")
            no_permissions_msg = l10n.get('no_permission', lang)
            try:
                await ctx.respond(no_permissions_msg)
            except Exception as e:
                 logging.error(f"Fehler beim Senden der 'no_permission'-Antwort: {e}")

    elif isinstance(error, commands.CommandNotFound):
        logging.warning(f"Unbekannter Befehl versucht: {ctx.command}")
        pass
    else:
        logging.error(f'Unbehandelter Fehler im Befehl {ctx.command}: {type(error).__name__} - {error}')
        print(f'Ignoring exception in command {ctx.command}:', file=sys.stderr)
        traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)
        general_error_msg = l10n.get('general_error', lang)
        try:
            if not ctx.interaction.response.is_done():
                 await ctx.respond(general_error_msg)
            else:
                 await ctx.followup.send(general_error_msg)
        except discord.NotFound:
             logging.warning("Interaction nicht gefunden beim Senden der allgemeinen Fehlermeldung.")
        except Exception as e:
            logging.error(f"Konnte allgemeine Fehlermeldung nicht senden: {e}")
@bot.event
async def on_ready():
    global EU_COUNTRY_CODES
    global SHOP_DATA
    SHOP_DATA = await load_shop_data()
    logging.info("Bot starting up...")
    def init_db():
        init_conn = sqlite3.connect(BASE_DIR / "antcheckbot.db")
        init_cursor = init_conn.cursor()
        init_cursor.executescript("""
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
                notified_at TIMESTAMP,
                excluded_species TEXT DEFAULT NULL,
                pending_feedback_until TIMESTAMP DEFAULT NULL,
                server_id INTEGER
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
            CREATE TABLE IF NOT EXISTS user_seen_products (
                user_id TEXT,
                product_id TEXT,
                PRIMARY KEY (user_id, product_id)
            );
            CREATE TABLE IF NOT EXISTS eu_countries (
                code TEXT PRIMARY KEY,
                name TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_notification_user_species_regions
            ON notifications(user_id, species, regions);
            CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);
            INSERT OR IGNORE INTO global_stats (key, value) VALUES ('deleted_notifications', 0);
        """)
        init_conn.commit()
        init_conn.close()
        logging.info("Database schema initialized/verified.")
    await bot.loop.run_in_executor(None, init_db)
    logging.info("Database initialization task completed.")
    try:
        EU_COUNTRY_CODES = await load_eu_countries()
        if isinstance(EU_COUNTRY_CODES, (list, set)):
            EU_COUNTRY_CODES = list(EU_COUNTRY_CODES)
            logging.info(f"EU Countries loaded: {len(EU_COUNTRY_CODES)} codes.")
        else:
            logging.error(f"Unexpected EU_COUNTRY_CODES type: {type(EU_COUNTRY_CODES)}")
            EU_COUNTRY_CODES = []
    except Exception as e:
        logging.error(f"Failed to load EU countries: {e}")
        EU_COUNTRY_CODES = []
    try:
        SHOP_DATA = await load_shop_data()
        logging.info(f"Shop data loaded: {len(SHOP_DATA)} shops.")
    except Exception as e:
        logging.error(f"Failed to load shop data: {e}")
        SHOP_DATA = {}
    bot.start_time = datetime.now()
    logging.info(f"Bot online: {bot.user}")
    try:
        await bot.sync_commands()
        logging.info("Commands synced successfully.")
    except Exception as e:
        logging.error(f"Failed to sync commands: {e}")
    logging.info("Starting background tasks...")
    try:
        if 'clean_old_notifications' in globals() and isinstance(clean_old_notifications, tasks.Loop): clean_old_notifications.start()
        if 'shop_data_loader' in globals() and isinstance(shop_data_loader, tasks.Loop): shop_data_loader.start()
        if 'check_availability' in globals() and isinstance(check_availability, tasks.Loop): check_availability.start()
        if 'update_bot_status' in globals() and isinstance(update_bot_status, tasks.Loop): update_bot_status.start()
        if 'optimize_db' in globals() and isinstance(optimize_db, tasks.Loop): optimize_db.start()
        if 'sync_ratings' in globals() and isinstance(sync_ratings, tasks.Loop): sync_ratings.start()
        if 'update_server_infos' in globals() and isinstance(update_server_infos, tasks.Loop): update_server_infos.start()
        if 'expire_pending_feedbacks' in globals() and isinstance(expire_pending_feedbacks, tasks.Loop): expire_pending_feedbacks.start()
        psutil.cpu_percent(interval=None)
        logging.info("Background tasks initiated.")
    except NameError as e:
         logging.error(f"Failed to start a background task - NameError: {e}. Make sure all task loops are defined before on_ready.")
    except Exception as e:
         logging.error(f"An error occurred starting background tasks: {e}", exc_info=True)
    logging.info(f"Bot final loaded")
if __name__ == "__main__":
    LOCALES_DIR.mkdir(exist_ok=True)
    bot.run(TOKEN)
