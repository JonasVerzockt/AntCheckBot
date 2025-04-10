import discord
from discord.ext import commands, tasks
import sqlite3
import json
import os
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
import asyncio

# Logging konfigurieren
def setup_logger():
    log_file = os.path.join(os.getcwd(), f"bot_log_{datetime.now().strftime('%Y%m%d')}.log")
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Erstelle einen RotatingFileHandler
    handler = RotatingFileHandler(log_file, maxBytes=1024*1024, backupCount=5, encoding='utf8')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    handler.setFormatter(formatter)

    # Füge den Handler zum Logger hinzu
    logger.addHandler(handler)

    # Füge auch einen StreamHandler hinzu, um in die Konsole zu schreiben
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# Bot-Konfiguration
TOKEN = "DEINTOKEN"  # Ersetze durch deinen Bot-Token
DATA_DIRECTORY = "PFAD"  # Ordner mit Produkt-JSON-Dateien
SHOPS_DATA_FILE = "shops_data.json"  # Datei mit den Shop-Informationen

# Bot-Setup
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# SQLite-Datenbank initialisieren
conn = sqlite3.connect("notifications.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    species TEXT,
    regions TEXT
)
""")
conn.commit()

# Shop-Daten laden (Shop-ID -> Land und Name)
def load_shop_data():
    logging.info("Lade Shop-Daten...")
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
        logging.info(f"Geladene Shops: {shop_data}")
    except FileNotFoundError:
        logging.error(f"{SHOPS_DATA_FILE} nicht gefunden.")
    return shop_data

SHOP_DATA = load_shop_data()

# Überprüfen, ob eine Art in den JSON-Dateien existiert (auch wenn nicht verfügbar)
def species_exists(species):
    logging.info(f"Prüfe, ob die Art '{species}' existiert...")
    for filename in os.listdir(DATA_DIRECTORY):
        if filename.endswith(".json"):
            file_path = os.path.join(DATA_DIRECTORY, filename)
            logging.info(f"Durchsuche Datei: {file_path}")
            with open(file_path, "r") as f:
                data = json.load(f)
                for product in data:
                    if "title" in product and species.lower() in product["title"].lower():
                        logging.info(f"Art '{species}' gefunden in Datei {file_path}")
                        return True
    logging.info(f"Art '{species}' nicht gefunden.")
    return False

# Überprüfen, ob eine Art in einer bestimmten Region verfügbar ist
def check_availability_for_species(species, regions):
    logging.info(f"Prüfe Verfügbarkeit für Art '{species}' in Regionen: {regions}")
    available_products = []
    for filename in os.listdir(DATA_DIRECTORY):
        if filename.endswith(".json"):
            file_path = os.path.join(DATA_DIRECTORY, filename)
            logging.info(f"Durchsuche Datei: {file_path}")
            with open(file_path, "r") as f:
                data = json.load(f)
                for product in data:
                    if "title" in product and species.lower() in product["title"].lower() and product.get("in_stock", False):
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
                                "changed_at": product["changed_at"],
                                "updated_at": product["updated_at"],
                                "shop_id": shop_id
                            })
                            logging.info(f"Verfügbares Produkt gefunden: {available_products[-1]}")
    logging.info(f"Gefundene verfügbare Produkte: {available_products}")
    return available_products

# Funktion, um die Verfügbarkeit sofort zu prüfen
async def trigger_availability_check(user_id, species, regions):
    logging.info(f"Starte sofortige Verfügbarkeitsprüfung für User-ID: {user_id}, Art: {species}, Regionen: {regions}")
    regions_list = [region.strip() for region in regions.split(",")]

    available_products = check_availability_for_species(species, regions_list)
    if available_products:
        try:
            user = await bot.fetch_user(int(user_id))
            for product in available_products:
                message = (
                    f"**Ameisenart:** {product['species']} - **Shopname:** {product['shop_name']} (**Region:** {SHOP_DATA[product['shop_id']]['country']})\n"
                    f"**Preis:** {product['min_price']} - {product['max_price']} {product['currency_iso']}\n"
                    f"[AntCheck URL](<{product['antcheck_url']}>) | [Shop URL](<{product['shop_url']}>)\n"
                    f"**Geändert am:** {product['changed_at']} | **Aktualisiert am:** {product['updated_at']}\n\n"
                    f"*Alle Daten sind von antcheck.info und Bot ist geschrieben von jonas_ants! Deine Anfrage ist nun aus der Datenbank gelöscht.*"
                )
                await user.send(message)
                logging.info(f"Nachricht an Benutzer {user.name} gesendet: {message}")
            try:
                cursor.execute("DELETE FROM notifications WHERE user_id=? AND species=? AND regions=?", (user_id, species, regions))
                conn.commit()
                logging.info(f"Spezifische Benachrichtigung für Benutzer-ID {user_id}, Art {species}, Regionen {regions} gelöscht.")
            except sqlite3.Error as e:
                logging.error(f"Fehler beim Löschen aus der Datenbank: {e}")
        except discord.errors.Forbidden as e:
            logging.error(f"Kann keine Nachricht an Benutzer {user_id} senden: {e}")
        except discord.errors.NotFound as e:
            logging.error(f"Benutzer {user_id} nicht gefunden: {e}")
        except Exception as e:
            logging.error(f"Unbekannter Fehler beim Senden der Nachricht: {e}")
    else:
        logging.info(f"Keine verfügbaren Produkte gefunden für User-ID: {user_id}, Art: {species}, Regionen: {regions}")

# Slash-Command für Benachrichtigungen
@bot.command()
async def notification(ctx, species: str, regions: str):
    regions_list = [region.strip() for region in regions.split(",")]
    logging.info(f"Befehl '!notification' ausgeführt von {ctx.author}. Art: {species}, Regionen: {regions_list}")

    # Länderkürzel validieren
    valid_regions = []
    invalid_regions = []
    for region in regions_list:
        if any(shop["country"] == region for shop in SHOP_DATA.values()):
            valid_regions.append(region)
        else:
            invalid_regions.append(region)

    if invalid_regions:
        await ctx.send(f"Ungültige Länderkürzel: {', '.join(invalid_regions)}. Gültige Länderkürzel sind: {', '.join(set(shop['country'] for shop in SHOP_DATA.values()))}")
        logging.info(f"Ungültige Länderkürzel: {invalid_regions}")
        return

    # Prüfen, ob der Benutzer diese Suche bereits hat
    cursor.execute("SELECT * FROM notifications WHERE user_id=? AND species=? AND regions=?", (str(ctx.author.id), species, ",".join(valid_regions)))
    existing_notification = cursor.fetchone()

    if existing_notification:
        await ctx.send("Du hast diese Benachrichtigung bereits eingerichtet.")
        logging.info("Benutzer hat diese Benachrichtigung bereits eingerichtet.")
        return

    if species_exists(species):
        user_id = str(ctx.author.id)
        cursor.execute("INSERT INTO notifications (user_id, species, regions) VALUES (?, ?, ?)",
                       (user_id, species, ",".join(valid_regions)))
        conn.commit()
        await ctx.send(f"Benachrichtigung für '{species}' in Regionen {', '.join(valid_regions)} wurde erfolgreich eingerichtet.")
        logging.info("Benachrichtigung erfolgreich gespeichert.")

        # Sofortige Auslösung der Prüfung
        await trigger_availability_check(user_id, species, ",".join(valid_regions))
    else:
        await ctx.send(f"Die Art '{species}' wurde nicht gefunden.")
        logging.info("Die Art wurde nicht gefunden und keine Benachrichtigung gespeichert.")

# Test funktion ob eine PN ankommt
@bot.command()
async def testnotification(ctx):
    """Sendet eine Testnachricht an den Benutzer, um PN-Benachrichtigungen zu testen."""
    try:
        user = ctx.author
        test_message = "Dies ist eine Testnachricht vom Bot. PN-Benachrichtigungen funktionieren!"
        await user.send(test_message)
        await ctx.send("Testnachricht erfolgreich gesendet! Überprüfe deine privaten Nachrichten.")
        logging.info(f"Testnachricht erfolgreich an Benutzer {user.name} gesendet.")
    except discord.errors.Forbidden:
        await ctx.send("Ich konnte dir keine PN senden. Bitte überprüfe deine Einstellungen und erlaube mir, dir Nachrichten zu senden.")
        logging.error(f"PN konnte nicht an Benutzer {ctx.author.name} gesendet werden.")
    except Exception as e:
        await ctx.send("Es gab einen Fehler beim Senden der Testnachricht.")
        logging.error(f"Fehler beim Senden der Testnachricht: {e}")

# Überwachung der Produkte (alle 5 Minuten)
@tasks.loop(minutes=5)
async def check_availability():
    logging.info("Starte planmäßige Überprüfung der Verfügbarkeit...")
    cursor.execute("SELECT * FROM notifications")
    notifications = cursor.fetchall()
    logging.info(f"Geladene Benachrichtigungen aus der Datenbank: {notifications}")

    for notification in notifications:
        user_id, species, regions = notification[1], notification[2], notification[3]

        await trigger_availability_check(user_id, species, regions)

# Event: Bot ist bereit
async def on_ready_event():
    setup_logger()
    logging.info(f"Bot ist online! Eingeloggt als {bot.user.name}")
    check_availability.start()

@bot.event
async def on_ready():
    await on_ready_event()

# Bot starten
bot.run(TOKEN)
