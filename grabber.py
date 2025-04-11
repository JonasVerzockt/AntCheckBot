#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File: grabber.py
Author: Jonas Beier
Date: 2025-04-11
Version: 1.1
Description:
    Dieses Skript ruft Daten von der AntCheck-API ab, speichert Shop- und Produktdaten 
    in JSON-Dateien und bereinigt alte Dateien basierend auf ihrem Alter. Es bietet 
    Funktionen für API-Datenabruf, Dateiverwaltung und Datenverarbeitung.

Dependencies:
    - requests
    - json
    - os
    - time
    - logging
    - RotatingFileHandler
    - datetime

Setup:
    1. Installiere die benötigten Python-Bibliotheken:
       pip install requests
    2. Setze deinen API-Schlüssel in der Variable `API_KEY`.
    3. Stelle sicher, dass das Skript Zugriff auf das Verzeichnis hat, in dem die JSON-Dateien gespeichert werden.

License: CC BY-NC 4.0
Contact: https://github.com/JonasVerzockt/
"""
import requests
import json
import os
import time
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

API_KEY = "KEY"
SHOPS_URL = f"https://antcheck.info/api/v2/ecommerce/shops?online=true&crawler_active=true&page=0&limit=-1&api_key={API_KEY}"

def setup_logger():
    log_file = os.path.join(os.getcwd(), f"grabber_log_{datetime.now().strftime('%Y%m%d')}.log")
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    handler = RotatingFileHandler(log_file, maxBytes=1024 * 1024, backupCount=5, encoding='utf8')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

setup_logger()
logger = logging.getLogger()

def delete_old_files(directory=".", hours=7):
    now = time.time()
    for filename in os.listdir(directory):
        if filename.startswith("products_shop_") and filename.endswith(".json"):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path):
                if now - os.stat(file_path).st_mtime > hours * 3600:
                    os.remove(file_path)
                    logger.info(f"Gelöscht: {filename}")

def fetch_api_data(api_url):
    response = requests.get(api_url)
    if response.status_code == 200:
        try:
            return response.json()
        except json.JSONDecodeError:
            logger.error("Fehler: Ungültige JSON-Antwort")
            return None
    logger.error(f"Fehler: HTTP-Statuscode {response.status_code}")
    return None

def fetch_products_for_shop(shop_id):
    products_url = f"https://antcheck.info/api/v2/ecommerce/products?shop_id={shop_id}&product_type=ants&page=0&limit=-1&api_key={API_KEY}"
    return fetch_api_data(products_url)

def main():
    logger.info("Skript gestartet")

    shops_data = fetch_api_data(SHOPS_URL)
    if not shops_data:
        logger.warning("Keine Shops-Daten gefunden")
        return

    with open("shops_data.json", "w") as f:
        json.dump(shops_data, f, indent=4)
        logger.info("Shops-Daten gespeichert")

    all_shops = shops_data
    for shop in all_shops:
        shop_id = shop.get("id")
        if shop_id:
            products_data = fetch_products_for_shop(shop_id)
            if products_data:
                filename = f"products_shop_{shop_id}.json"
                with open(filename, "w") as f:
                    json.dump(products_data, f, indent=4)
                logger.info(f"Shop {shop_id}: Produkte gespeichert")
        else:
            logger.warning("Warnung: Shop ohne ID gefunden")

    delete_old_files()
    
    logger.info("Skript beendet")

if __name__ == "__main__":
    main()