import sys
import signal
import argparse
import json
from urllib.parse import urlunparse

import asyncio
import aiohttp
import tqdm

# Restore default Ctrl-C handler for faster process shutdown
signal.signal(signal.SIGINT, signal.SIG_DFL)

ITEM_LIST_URL = "http://api.xivdb.com/search"

CATEGORIES = {
    "Food": 46,
    "Medicine": 44
}

FETCH_SEMAPHORE: asyncio.Semaphore

async def wait_with_progress(coros, desc=None, unit=None):
    for f in tqdm.tqdm(asyncio.as_completed(coros), total=len(coros), desc=desc, unit=unit):
        yield await f

def parse_item_links_page(text):
    data = json.loads(text)
    urls = map(lambda x: x['url_api'], data['items']['results'])
    pages = data['items']['paging']['total']
    return urls, pages

async def fetch_item_links_page(session, category, page):
    params = {
        "attributes": "71|gt|1|0,70|gt|1|0,11|gt|1|0",
        "item_ui_category|et": CATEGORIES[category],
        "attributes_andor": "or",
        "one": "items",
        "page": page
    }                                       

    while True:
        try:
            async with FETCH_SEMAPHORE:
                async with session.get(ITEM_LIST_URL, params=params) as res:
                    data = parse_item_links_page(await res.text())
                    break
        except:
            #print("ERROR: Could not parse page -- retrying after delay", file=sys.stderr)
            pass

    return data

async def fetch_item_urls(session, category):
    urls = []
    page = 1
    while True:
        page_urls, total = await fetch_item_links_page(session, category, page)
        urls += page_urls
        if page < total:
            page += 1
        else:
            break
    return urls

async def fetch_page(session, url):
    while True:
        try:
            async with FETCH_SEMAPHORE:
                async with session.get(url) as res:
                    data = json.loads(await res.text())
                    break
        except:
            #print("ERROR: Could not parse page -- retrying after delay", file=sys.stderr)
            pass
    return data

async def fetch_item(session, url):
    data = await fetch_page(session, url)
    
    food = {
        "name": data["name_en"],
        "hq": False,
        "ilvl": data["level_item"]
    }

    food_hq = {
        "name": data["name_en"],
        "hq": True,
        "ilvl": data["level_item"]
    }

    for attr in data["attributes_params"]:
        if attr["id"] == 70:
            food["craftsmanship_value"] = attr["value"]
            food["craftsmanship_percent"] = attr["percent"]
            food_hq["craftsmanship_value"] = attr["value_hq"]
            food_hq["craftsmanship_percent"] = attr["percent_hq"]
        if attr["id"] == 71:
            food["control_value"] = attr["value"]
            food["control_percent"] = attr["percent"]
            food_hq["control_value"] = attr["value_hq"]
            food_hq["control_percent"] = attr["percent_hq"]
        if attr["id"] == 11:
            food["cp_value"] = attr["value"]
            food["cp_percent"] = attr["percent"]
            food_hq["cp_value"] = attr["value_hq"]
            food_hq["cp_percent"] = attr["percent_hq"]

    return [food, food_hq]

async def fetch_items(session, category, urls):
    results = wait_with_progress(
        [fetch_item(session, url) for url in urls],
        desc=f"Fetching %s" % category,
        unit=""
    )

    food = []
    async for r in results:
        food.extend(r)

    return food

async def fetch_all_items(session, category):
    results = wait_with_progress(
        [ fetch_item_urls(session, category) ],
        desc=f"Fetching %s ids" % category,
        unit=""
    )

    urls = []
    async for r in results:
        urls.extend(r)

    food = await fetch_items(session, category, urls)
    food.sort(key=lambda r: (r['ilvl'], r['name'], r['hq']), reverse=True)
    return food

async def scrape_items(session):
    for category in CATEGORIES.keys():
        recipes = await fetch_all_items(session, category)
        with open("out/%s.json" % category, mode="wt", encoding="utf-8") as db_file:
            json.dump(recipes, db_file, indent=2, sort_keys=True, ensure_ascii=False)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        "--concurrency",
        help="Max number of concurrent requests to Lodestone servers. [Default: 4]",
        default=4,
        metavar="N"
    )
    args = parser.parse_args()

    loop = asyncio.get_event_loop()

    global FETCH_SEMAPHORE
    FETCH_SEMAPHORE = asyncio.Semaphore(int(args.concurrency), loop=loop)
    session = aiohttp.ClientSession(loop=loop)

    try:
        loop.run_until_complete(scrape_items(session))
    except KeyboardInterrupt:
        pass
    finally:
        session.close()
        loop.close()

if __name__ == '__main__':
    main()
