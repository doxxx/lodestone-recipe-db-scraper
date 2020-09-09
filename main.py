import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import sys
import time
from typing import Mapping, Sequence
from urllib.parse import urlunparse

import aiohttp
import lxml.html as html
import tqdm

# type definitions
LanguageMapping = Mapping[str,Mapping[str,str]]

# Restore default Ctrl-C handler for faster process shutdown
signal.signal(signal.SIGINT, signal.SIG_DFL)

RECIPE_LIST_URL = "http://na.finalfantasyxiv.com/lodestone/playguide/db/recipe/"
ITEM_LIST_URL = "http://na.finalfantasyxiv.com/lodestone/playguide/db/item/"

CACHE_EXPIRY = 60*60*12 # 12 hours, in seconds

LANG_HOSTS = {
    "en": "na.finalfantasyxiv.com",
    "ja": "jp.finalfantasyxiv.com",
    "fr": "fr.finalfantasyxiv.com",
    "de": "de.finalfantasyxiv.com",
}

CLASSES = [
    "carpenter",
    "blacksmith",
    "armorer",
    "goldsmith",
    "leatherworker",
    "weaver",
    "alchemist",
    "culinarian",
]

# recipe level -> [ 0-star adjustment, 1-star adjustment, ... ]
LEVEL_DIFF = {
    # verified against app
    50: [ 0, 5, 20, 40, 60 ], # 50, 55, 70, 90, 110
    # unconfirmed from desynthesis results
    51: [ 69 ], # 120
    52: [ 73 ], # 125
    53: [ 77 ], # 130
    54: [ 79 ], # 133
    55: [ 81 ], # 136
    56: [ 83 ], # 139
    57: [ 85 ], # 142
    58: [ 87 ], # 145
    59: [ 89 ], # 148
    60: [ 90, 100, 120, 150, 190 ], # 150, 160, 180, 210, 250
    61: [ 199 ], # 260
    62: [ 203 ], # 265
    63: [ 207 ], # 270
    64: [ 209 ], # 273
    65: [ 211 ], # 276
    66: [ 213 ], # 279
    67: [ 215 ], # 282
    68: [ 217 ], # 285
    69: [ 219 ], # 288
    70: [ 220, 230, 250, 280, 310 ], # 290, 300, 320, 350, 380
    71: [ 319 ], # 390
    72: [ 323 ], # 395
    73: [ 327 ], # 400
    74: [ 329 ], # 403
    75: [ 331 ], # 406
    76: [ 333 ], # 409
    77: [ 335 ], # 412
    78: [ 337 ], # 415
    79: [ 339 ], # 418
    80: [ 350, 360, 370, 400, 430 ], # 430, 440, 450, 480, 510
}

MAX_LEVEL = 80
LEVEL_RANGES = ["{0}-{1}".format(start, start + 4) for start in range(1, MAX_LEVEL, 5)]
NUM_LEVEL_RANGES = len(LEVEL_RANGES)
NUM_ADDITIONAL_RECIPE_CATEGORIES = 7
RECIPE_LINK_CATEGORIES = ['%d' % (level_range,) for level_range in range(0, NUM_LEVEL_RANGES)] + \
                         ['c%d' % (cat,) for cat in range(1, NUM_ADDITIONAL_RECIPE_CATEGORIES + 1)]

EMBED_CODE_RE = re.compile("\\[db:[a-z]+=([0-9a-f]+)]")
ASPECT_RE = re.compile("Aspect: (.+)")
RECIPE_CRAFTSMANSHIP_RE = re.compile("Craftsmanship (?:Required|Recommended): ([0-9]+)")
RECIPE_CONTROL_RE = re.compile("Control (?:Required|Recommended): ([0-9]+)")
ITEM_CRAFTSMANSHIP_RE = re.compile(r"Craftsmanship \+([0-9]+)% \(Max ([0-9]+)\)")
ITEM_CONTROL_RE = re.compile(r"Control \+([0-9]+)% \(Max ([0-9]+)\)")
ITEM_CP_RE = re.compile(r"CP \+([0-9]+)% \(Max ([0-9]+)\)")

ITEM_CAT_MEDICINE = 44
ITEM_CAT_MEAL = 46

ITEM_CATEGORIES = {
    44: "Medicine",
    46: "Meal",
}

FETCH_SEMAPHORE: asyncio.Semaphore


def logInfo(msg):
    print(msg, end="\n", file=sys.stderr)


def logError(msg):
    print(f"\nERROR: {msg}", end="\n", file=sys.stderr)


async def wait_with_progress(coros: list, desc: str = None, unit: str = None):
    for f in tqdm.tqdm(asyncio.as_completed(coros), total=len(coros), desc=desc, unit=unit):
        yield await f


def get_cache_key(url: str, **kwargs):
    m = hashlib.sha1()
    m.update(bytes(url, "UTF-8"))
    sorted_keys = list(kwargs.keys())
    sorted_keys.sort()
    for k in sorted_keys:
        m.update(bytes(str(k), "UTF-8"))
        m.update(b"=")
        m.update(bytes(str(kwargs[k]), "UTF-8"))
        m.update(b";")
    return m.hexdigest()


def get_cached_text(url: str, **kwargs):
    key = get_cache_key(url, **kwargs)
    os.makedirs(".cache", exist_ok=True)
    filename = f".cache/{key}"
    try:
        s = os.stat(filename)
        if s.st_mtime < time.time() - CACHE_EXPIRY:
            os.remove(filename)
            return None
        with open(filename, mode="rt", encoding="UTF-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def cache_text(text: str, url: str, **kwargs):
    key = get_cache_key(url, **kwargs)
    os.makedirs(".cache", exist_ok=True)
    with open(f".cache/{key}", mode="wt", encoding="UTF-8") as f:
        f.write(text)


async def fetch(session: aiohttp.ClientSession, url: str, **kwargs):
    # TODO: cache files
    cached_text = get_cached_text(url, **kwargs)
    if cached_text is not None:
        return cached_text

    err_count = 0
    while err_count < 5:
        # noinspection PyBroadException
        try:
            async with FETCH_SEMAPHORE:
                async with session.get(url, **kwargs) as res:
                    if res.status == 429:
                        retry_after = int(res.headers["retry-after"] or '5')
                        await asyncio.sleep(retry_after)
                        continue
                    elif res.status != 200:
                        raise Exception(f"{res.status} {res.reason}")
                    text = await res.text()
                    cache_text(text, url, **kwargs)
                    return text
        except SystemExit:
            raise
        except:
            err_count += 1
            await asyncio.sleep(5)
            pass
    logError(f"Could not load page after 5 tries: {url}")
    raise SystemExit


def parse_links_page(text: str) -> (Sequence[str], int, int):
    tree = html.fromstring(text)
    rel_links = tree.xpath("//div/@data-ldst-href")
    links = map(str, rel_links)
    show_end = int(tree.xpath("//span[@class='show_end']/text()")[0])
    total = int(tree.xpath("//span[@class='total']/text()")[0])
    return links, show_end, total


async def fetch_recipe_links_page(session: aiohttp.ClientSession, cls: str, category: str, page: int) -> (Sequence[str], int, int):
    params = {
        "category2": CLASSES.index(cls),
        "category3": category,
        "page": page,
    }
    return parse_links_page(await fetch(session, RECIPE_LIST_URL, params=params))


async def fetch_recipe_links_range(session: aiohttp.ClientSession, cls: str, category: str):
    links = []
    page = 1
    while True:
        page_links, show_end, total = await fetch_recipe_links_page(session, cls, category, page)
        links += page_links
        if show_end < total:
            page += 1
        else:
            break
    return links


async def fetch_recipe_links(session: aiohttp.ClientSession, cls: str):
    results = wait_with_progress(
        [fetch_recipe_links_range(session, cls, category) for category in RECIPE_LINK_CATEGORIES],
        desc=f"Fetching {cls.capitalize()} links",
        unit=""
    )

    links = []
    async for r in results:
        links.extend(r)

    return links


def make_lang_url(lang: str, rel_link: str):
    return urlunparse(("http", LANG_HOSTS[lang], rel_link, "", "", ""))


async def fetch_pages_all_langs(session: aiohttp.ClientSession, rel_link: str):
    pages = {}

    for lang in LANG_HOSTS:
        pages[lang] = html.fromstring(await fetch(session, make_lang_url(lang, rel_link)))

    return pages


def extract_db_id(tree) -> str:
    embed_code = tree.xpath("//div[@class='embed_code_txt']//div[contains(text(), 'db:')]/text()")[0]
    match = EMBED_CODE_RE.match(embed_code)
    if match is None:
        raise Exception("embed id not found")
    return match.group(1)


async def fetch_recipe(session: aiohttp.ClientSession, rel_link: str):
    pages = await fetch_pages_all_langs(session, rel_link)

    tree = pages["en"]

    recipe_id = extract_db_id(tree)

    detail_box = tree.xpath("//div[@class='recipe_detail item_detail_box']")[0]
    base_level = int(detail_box.xpath("//span[@class='db-view__item__text__level__num']/text()")[0])
    stars = None
    level_adjustment = 0
    if base_level in LEVEL_DIFF:
        stars = len(detail_box.xpath("//div[@class='db-view__item__text__level']//span[contains(@class, 'star')]"))
        try:
            level_adjustment = LEVEL_DIFF[base_level][stars]
        except IndexError:
            logError(f"Unsupported number of stars ({stars}) for level {base_level}.")
            raise SystemExit

    level = base_level + level_adjustment

    craft_data = tree.xpath("//ul[@class='db-view__recipe__craftdata']")[0]
    difficulty = int(craft_data.xpath("li[span='Difficulty']/text()")[0])
    durability = int(craft_data.xpath("li[span='Durability']/text()")[0])
    max_quality = int(craft_data.xpath("li[span='Maximum Quality']/text()")[0])

    # Base level 51 recipes of difficulty 169 or 339 are adjusted to level 115
    # instead of the default 120 that other level 51 recipes are adjusted to.

    if ((base_level == 51 and (difficulty == 169 or difficulty == 339)) or
            (base_level == 61 and (difficulty == 1116 or difficulty == 558))):
        level -= 5
    if base_level == 60 and stars == 3 and difficulty == 1764:
        level += 10

    aspect = None
    suggested_craftsmanship = None
    suggested_control = None

    craft_conditions = tree.xpath("//dl[@class='db-view__recipe__crafting_conditions']")[0]
    for characteristic in craft_conditions.xpath("dt[text()='Characteristics']/../dd/text()"):
        characteristic = characteristic.strip()
        match = ASPECT_RE.match(characteristic)
        if not match is None:
            aspect = match.group(1)
        match = RECIPE_CRAFTSMANSHIP_RE.match(characteristic)
        if not match is None:
            suggested_craftsmanship = int(match.group(1))
        match = RECIPE_CONTROL_RE.match(characteristic)
        if not match is None:
            suggested_control = int(match.group(1))

    recipe = {
        "id": recipe_id,
        "name": {},
        "baseLevel": base_level,
        "level": level,
        "difficulty": difficulty,
        "durability": durability,
        "maxQuality": max_quality,
    }

    if stars:
        recipe["stars"] = stars

    if aspect:
        recipe["aspect"] = aspect

    if suggested_craftsmanship:
        recipe["suggestedCraftsmanship"] = suggested_craftsmanship

    if suggested_control:
        recipe["suggestedControl"] = suggested_control

    for lang in LANG_HOSTS:
        tree = pages[lang]
        recipe["name"][lang] = str(tree.xpath("//h2[contains(@class,'db-view__item__text__name')]/text()")[0]).strip()

    return recipe


async def fetch_recipes(session: aiohttp.ClientSession, cls: str, links: Sequence[str]):
    recipes = wait_with_progress(
        [fetch_recipe(session, link) for link in links],
        desc=f"Fetching {cls.capitalize()} recipes",
        unit=""
    )

    return [r async for r in recipes]


async def fetch_class(session: aiohttp.ClientSession, additional_languages: LanguageMapping, cls: str):
    links = await fetch_recipe_links(session, cls)
    recipes = await fetch_recipes(session, cls, links)
    recipes.sort(key=lambda r: (r['level'], r['name']['en']))
    for recipe in recipes:
        for lang in additional_languages.keys():
            names = additional_languages[lang]
            english_name = recipe['name']['en']
            recipe['name'][lang] = names.get(english_name) or english_name
    return recipes


async def scrape_classes(session: aiohttp.ClientSession, additional_languages: LanguageMapping, classes: Sequence[str]):
    for cls in classes:
        recipes = await fetch_class(session, additional_languages, cls)
        with open(f"out/{cls.capitalize()}.json", mode="wt", encoding="utf-8") as db_file:
            json.dump(recipes, db_file, indent=2, sort_keys=True, ensure_ascii=False)


async def fetch_item_links_page(session: aiohttp.ClientSession, category: int, page: int):
    params = {
        "category2": 5,
        "category3": category,
        "page": page,
    }
    return parse_links_page(await fetch(session, ITEM_LIST_URL, params=params))


async def fetch_item_links_range(session: aiohttp.ClientSession, category: int):
    links = []
    page = 1
    while True:
        page_links, show_end, total = await fetch_item_links_page(session, category, page)
        links += page_links
        if show_end < total:
            page += 1
        else:
            break
    return links


async def fetch_item_links(session: aiohttp.ClientSession, category: int):
    results = wait_with_progress(
        [fetch_item_links_range(session, category)],
        desc=f"Fetching {ITEM_CATEGORIES[category]} links",
        unit=""
    )

    links = []
    async for r in results:
        links.extend(r)

    return links


def extract_item_attr(text, item):
    found_attr = False

    for m in ITEM_CRAFTSMANSHIP_RE.finditer(text):
        found_attr = True
        item["craftsmanship_percent"] = int(m.group(1))
        item["craftsmanship_value"] = int(m.group(2))

    for m in ITEM_CONTROL_RE.finditer(text):
        found_attr = True
        item["control_percent"] = int(m.group(1))
        item["control_value"] = int(m.group(2))

    for m in ITEM_CP_RE.finditer(text):
        found_attr = True
        item["cp_percent"] = int(m.group(1))
        item["cp_value"] = int(m.group(2))

    return found_attr


async def fetch_item(session: aiohttp.ClientSession, rel_link: str) -> (dict, dict):
    pages = await fetch_pages_all_langs(session, rel_link)

    tree = pages["en"]

    item_id = extract_db_id(tree)

    item_nq = {
        "id": item_id,
        "name": {},
        "hq": False,
    }

    item_hq = {
        "id": item_id,
        "name": {},
        "hq": True,
    }

    info_text_div = tree.xpath("//div[@class='db-view__info_text']")[0]
    info_text_nq = "".join(info_text_div.xpath("//ul[@class='sys_nq_element']//text()")).strip()
    info_text_hq = "".join(info_text_div.xpath("//ul[@class='sys_hq_element']//text()")).strip()

    has_nq_attr = extract_item_attr(info_text_nq, item_nq)
    has_hq_attr = extract_item_attr(info_text_hq, item_hq)
    if not has_nq_attr and not has_hq_attr:
        return []

    for lang in LANG_HOSTS:
        tree = pages[lang]
        item_nq["name"][lang] = str(tree.xpath("//h2[contains(@class,'db-view__item__text__name')]/text()")[0]).strip()
        item_hq["name"][lang] = str(tree.xpath("//h2[contains(@class,'db-view__item__text__name')]/text()")[0]).strip()

    return [item_nq, item_hq]


async def fetch_items(session: aiohttp.ClientSession, links: Sequence[str]):
    items = wait_with_progress(
        [fetch_item(session, link) for link in links],
        desc=f"Fetching items",
        unit=""
    )

    return [item async for nq_hq in items for item in nq_hq]


async def fetch_items_category(session: aiohttp.ClientSession, additional_languages: LanguageMapping, category: int):
    links = await fetch_item_links(session, category)
    items = await fetch_items(session, links)
    items.sort(key=lambda r: r['name']['en'])
    for item  in items:
        for lang in additional_languages.keys():
            names = additional_languages[lang]
            english_name = item['name']['en']
            item['name'][lang] = names.get(english_name) or english_name
    return items


async def scrape_buffs(session: aiohttp.ClientSession, additional_languages: LanguageMapping):
    for category in ITEM_CATEGORIES.keys():
        category_name = ITEM_CATEGORIES[category]
        items = await fetch_items_category(session, additional_languages, category)
        with open(f"out/{category_name}.json", mode="wt", encoding="utf-8") as db_file:
            json.dump(items, db_file, indent=2, sort_keys=True, ensure_ascii=False)


def load_additional_languages(specs: Sequence[str]) -> LanguageMapping:
    additional_languages = {}
    for s in specs:
        lang, path = s.split("=", 2)
        with open(path, mode="rt", encoding="utf-8") as fp:
            print(f"Loading additional language '{lang}' from: {path}")
            additional_languages[lang] = json.load(fp)
    return additional_languages


async def async_main(args):
    if not args.recipes and not args.buffs:
        print("ERROR: One or more of the following options must be provided: --recipes, --buffs", file=sys.stderr)
        return

    if args.clear_cache:
        shutil.rmtree(".cache")

    if args.lang_file:
        additional_languages = load_additional_languages(args.lang_file)
    else:
        additional_languages = {}

    global FETCH_SEMAPHORE
    FETCH_SEMAPHORE = asyncio.Semaphore(args.concurrency)
    session = aiohttp.ClientSession()

    try:
        if args.recipes:
            classes = [cls.lower() for cls in args.recipes]
            if "all" in classes:
                classes = CLASSES
            await scrape_classes(session, additional_languages, classes)
        if args.buffs:
            await scrape_buffs(session, additional_languages)
    except KeyboardInterrupt:
        pass
    finally:
        await session.close()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        "--concurrency",
        metavar="N",
        help="Max number of concurrent requests to Lodestone servers. [Default: 8]",
        default=8,
        type=int,
    )
    parser.add_argument(
        "-l",
        "--lang-file",
        metavar="LANG=FILE",
        help="Language code and path to file that defines mappings from English names to another language.",
        action="append",
    )
    parser.add_argument(
        "-r",
        "--recipes",
        metavar="CLASS",
        help=f"Scrape recipes for a class. Can be specified more than once to collect multiple classes, or use 'all' to collect all classes. Classes: {', '.join(CLASSES)}",
        action="append",
        choices=['all'] + CLASSES,
    )
    parser.add_argument(
        "-b",
        "--buffs",
        help="Scrap buff items.",
        action="store_true"
    )
    parser.add_argument(
        "--clear-cache",
        help="Clear the download cache.",
        action="store_true",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(async_main(args))
    finally:
        loop.close()


if __name__ == '__main__':
    main()
