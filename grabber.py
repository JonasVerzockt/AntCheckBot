#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File: grabber.py
Author: Jonas Beier
Date: 2025-04-11
Version: 1.0
Description:
    Dieses Skript ruft Daten von der AntCheck-API ab, speichert Shop- und Produktdaten 
    in JSON-Dateien und bereinigt alte Dateien basierend auf ihrem Alter. Es bietet 
    Funktionen für API-Datenabruf, Dateiverwaltung und Datenverarbeitung.

Dependencies:
    - requests
    - json
    - os
    - time

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

# API-Schlüssel für den Zugriff auf die AntCheck-API
API_KEY = "DEINKEY"
# URL für den Abruf von Shop-Daten von der AntCheck-API
SHOPS_URL = f"https://antcheck.info/api/v2/ecommerce/shops?online=true&crawler_active=true&page=0&limit=-1&api_key={API_KEY}"

def delete_old_files(directory=".", hours=7):
    """
    Löscht alte JSON-Dateien im angegebenen Verzeichnis, die älter als die angegebene Anzahl von Stunden sind.
    """
    now = time.time()
    for filename in os.listdir(directory):
        # Überprüft, ob die Datei mit "products_shop_" beginnt und mit ".json" endet
        if filename.startswith("products_shop_") and filename.endswith(".json"):
            file_path = os.path.join(directory, filename)
            # Überprüft, ob es sich um eine Datei handelt (kein Verzeichnis)
            if os.path.isfile(file_path):
                # Berechnet das Alter der Datei in Sekunden
                if now - os.stat(file_path).st_mtime > hours * 3600:
                    os.remove(file_path)
                    print(f"Gelöscht: {filename}")

def fetch_api_data(api_url):
    """
    Ruft Daten von der angegebenen API-URL ab und gibt die JSON-Antwort zurück.
    Gibt None zurück, wenn ein Fehler auftritt.
    """
    try:
        response = requests.get(api_url)
        response.raise_for_status()  # Wirft eine Ausnahme für HTTP-Fehler
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Fehler beim Abrufen von Daten von {api_url}: {e}")
        return None
    except json.JSONDecodeError:
        print("Fehler: Ungültige JSON-Antwort")
        return None

def fetch_products_for_shop(shop_id):
    """
    Ruft Produktdaten für einen bestimmten Shop von der AntCheck-API ab.
    """
    products_url = f"https://antcheck.info/api/v2/ecommerce/products?shop_id={shop_id}&product_type=ants&page=0&limit=-1&api_key={API_KEY}"
    return fetch_api_data(products_url)

def main():
    """
    Hauptfunktion, die Shop- und Produktdaten abruft und in JSON-Dateien speichert.
    """
    # Ruft die Shop-Daten von der API ab
    shops_data = fetch_api_data(SHOPS_URL)
    if not shops_data:
        return

    # Speichert die Shop-Daten in einer JSON-Datei
    with open("shops_data.json", "w") as f:
        json.dump(shops_data, f, indent=4)

    # Iteriert über alle Shops in den abgerufenen Daten
    all_shops = shops_data
    for shop in all_shops:
        shop_id = shop.get("id")
        if shop_id:
            # Ruft die Produktdaten für den aktuellen Shop ab
            products_data = fetch_products_for_shop(shop_id)
            if products_data:
                # Speichert die Produktdaten in einer JSON-Datei
                filename = f"products_shop_{shop_id}.json"
                with open(filename, "w") as f:
                    json.dump(products_data, f, indent=4)
                print(f"Shop {shop_id}: Produkte gespeichert")
        else:
            print("Warnung: Shop ohne ID gefunden")

    # Löscht alte Produktdateien
    delete_old_files()

if __name__ == "__main__":
    main()
