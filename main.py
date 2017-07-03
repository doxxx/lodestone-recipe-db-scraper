import sys
import signal
import argparse
import json
import re
from urllib.parse import urlunparse

import lxml.html as html
import asyncio
import aiohttp
import tqdm

# Restore default Ctrl-C handler for faster process shutdown
signal.signal(signal.SIGINT, signal.SIG_DFL)

RECIPE_LIST_URL = "http://na.finalfantasyxiv.com/lodestone/playguide/db/recipe/"

LANG_HOSTS = {
    "en": "na.finalfantasyxiv.com",
    "ja": "jp.finalfantasyxiv.com",
    "fr": "fr.finalfantasyxiv.com",
    "de": "de.finalfantasyxiv.com",
}

CLASSES = [
    "Carpenter",
    "Blacksmith",
    "Armorer",
    "Goldsmith",
    "Leatherworker",
    "Weaver",
    "Alchemist",
    "Culinarian",
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
    60: [ 90, 100, 110, 120, 130 ], # 150, 160, 170, 180, 190
}

LEVEL_RANGE = ["{0}-{1}".format(start, start + 4) for start in range(1, 60, 5)]
NUM_LEVEL_RANGES = len(LEVEL_RANGE)

ASPECT_RE = re.compile("Aspect: (.+)")

FETCH_SEMAPHORE: asyncio.Semaphore

async def wait_with_progress(coros, desc=None, unit=None):
    for f in tqdm.tqdm(asyncio.as_completed(coros), total=len(coros), desc=desc, unit=unit):
        yield await f

def parse_recipe_links_page(text):
    tree = html.fromstring(text)
    rel_links = tree.xpath("//div/@data-ldst-href")
    links = map(str, rel_links)
    show_end = int(tree.xpath("//span[@class='show_end']/text()")[0])
    total = int(tree.xpath("//span[@class='total']/text()")[0])
    return links, show_end, total

async def fetch_recipe_links_page(session, cls, level_range, page):
    params = {
        "category2": CLASSES.index(cls),
        "category3": level_range,
        "page": page,
    }

    async with FETCH_SEMAPHORE:
        async with session.get(RECIPE_LIST_URL, params=params) as res:
            return parse_recipe_links_page(await res.text())

async def fetch_recipe_links_range(session, cls, level_range):
    links = []
    page = 1
    while True:
        page_links, show_end, total = await fetch_recipe_links_page(session, cls, level_range, page)
        links += page_links
        if show_end < total:
            page += 1
        else:
            break
    return links

async def fetch_recipe_links(session, cls):
    results = wait_with_progress(
        [
            fetch_recipe_links_range(session, cls, level_range)
            for level_range in range(0, NUM_LEVEL_RANGES)]
        ,
        desc=f"Fetching {cls} links",
        unit=""
    )

    links = []
    async for r in results:
        links.extend(r)

    return links


def make_recipe_url(lang, rel_link):
    return urlunparse(("http", LANG_HOSTS[lang], rel_link, "", "", ""))

async def fetch_recipe_page(session, lang, rel_link):
    while True:
        try:
            async with FETCH_SEMAPHORE:
                async with session.get(make_recipe_url(lang, rel_link)) as res:
                    tree = html.fromstring(await res.text())
                    break
        except:
            print("ERROR: Could not parse page -- retrying after delay", file=sys.stderr)
            pass
    return tree

async def fetch_recipe_pages(session, rel_link):
    pages = {}

    for lang in LANG_HOSTS:
        pages[lang] = await fetch_recipe_page(session, lang, rel_link)

    return pages


async def fetch_recipe(session, rel_link):
    pages = await fetch_recipe_pages(session, rel_link)

    tree = pages["en"]

    detail_box = tree.xpath("//div[@class='recipe_detail item_detail_box']")[0]
    base_level = int(detail_box.xpath("//span[@class='db-view__item__text__level__num']/text()")[0])
    stars = None
    level_adjustment = 0
    if base_level in LEVEL_DIFF:
        stars = len(detail_box.xpath("//div[@class='db-view__item__text__level']//span[contains(@class, 'star')]"))
        level_adjustment = LEVEL_DIFF[base_level][stars]
    level = base_level + level_adjustment

    craft_data = tree.xpath("//ul[@class='db-view__recipe__craftdata']")[0]
    difficulty = int(craft_data.xpath("li[span='Difficulty']/text()")[0])
    durability = int(craft_data.xpath("li[span='Durability']/text()")[0])
    maxQuality = int(craft_data.xpath("li[span='Maximum Quality']/text()")[0])

    # Base level 51 recipes of difficulty 169 or 339 are adjusted to level 115
    # instead of the default 120 that other level 51 recipes are adjusted to.

    if base_level == 51 and (difficulty == 169 or difficulty == 339):
        level -= 5

    aspect = None

    craft_conditions = tree.xpath("//dl[@class='db-view__recipe__crafting_conditions']")[0]
    for characteristic in craft_conditions.xpath("dt[text()='Characteristics']/../dd/text()"):
        characteristic = characteristic.strip()
        match = ASPECT_RE.match(characteristic)
        if not match is None:
            aspect = match.group(1)

    recipe = {
        "name" : {},
        "baseLevel" : base_level,
        "level" : level,
        "difficulty" : difficulty,
        "durability" : durability,
        "maxQuality" : maxQuality,
    }

    if stars:
        recipe["stars"] = stars

    if aspect:
        recipe["aspect"] = aspect

    for lang in LANG_HOSTS:
        tree = pages[lang]
        recipe["name"][lang] = str(tree.xpath("//h2[contains(@class,'db-view__item__text__name')]/text()")[0]).strip()

    return recipe

async def fetch_recipes(session, cls, links):
    recipes = wait_with_progress(
        [fetch_recipe(session, link) for link in links],
        desc=f"Fetching {cls} recipes",
        unit=""
    )

    return [r async for r in recipes]


async def fetch_class(session, additional_languages, cls):
    links = await fetch_recipe_links(session, cls)
    recipes = await fetch_recipes(session, cls, links)
    recipes.sort(key=lambda r: (r['level'], r['name']['en']))
    for r in recipes:
        for lang in additional_languages.keys():
            names = additional_languages[lang]
            english_name = r['name']['en']
            r['name'][lang] = names[english_name] or english_name
    return recipes

async def scrape_to_file(session, additional_languages, cls):
    recipes = await fetch_class(session, additional_languages, cls)
    with open("out/" + cls + ".json", mode="wt", encoding="utf-8") as db_file:
        json.dump(recipes, db_file, indent=2, sort_keys=True, ensure_ascii=False)

async def scrape_classes(session, additional_languages):
    for cls in CLASSES:
        await scrape_to_file(session, additional_languages, cls)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        "--concurrency",
        help="Max number of concurrent requests to Lodestone servers. [Default: 8]",
        default=8,
        metavar="N"
    )
    parser.add_argument(
        "-l",
        "--lang-file",
        help="Language code and path to file that defines mappings from English recipe names to another language.",
        metavar="LANG=FILE",
        action="append"
    )
    args = parser.parse_args()

    # Load additional language files
    additional_languages = {}
    for f in args.lang_file:
        lang, path = f.split("=", 2)
        with open(path, mode="rt", encoding="utf-8") as fp:
            print(f"Loading additional langage '{lang}' from: {path}")
            additional_languages[lang] = json.load(fp)

    loop = asyncio.get_event_loop()

    global FETCH_SEMAPHORE
    FETCH_SEMAPHORE = asyncio.Semaphore(int(args.concurrency), loop=loop)
    session = aiohttp.ClientSession(loop=loop)

    try:
        loop.run_until_complete(scrape_classes(session, additional_languages))
    except KeyboardInterrupt:
        pass
    finally:
        session.close()
        loop.close()

if __name__ == '__main__':
    main()
