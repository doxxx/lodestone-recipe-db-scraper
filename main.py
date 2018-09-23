import signal
import argparse
import json
import re
import sys
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
    70: [ 220, 230, 250, 280, 320 ], # 290, 300, 320, 350, 390
}

LEVEL_RANGE = ["{0}-{1}".format(start, start + 4) for start in range(1, 70, 5)]
NUM_LEVEL_RANGES = len(LEVEL_RANGE)

EMBED_CODE_RE = re.compile("\\[db:recipe=([0-9a-f]+)]")

ASPECT_RE = re.compile("Aspect: (.+)")

FETCH_SEMAPHORE: asyncio.Semaphore


def logInfo(msg):
    print(msg, end="\n", file=sys.stderr)


def logError(msg):
    print(f"\nERROR: {msg}", end="\n", file=sys.stderr)


async def wait_with_progress(coros: list, desc: str = None, unit: str = None):
    for f in tqdm.tqdm(asyncio.as_completed(coros), total=len(coros), desc=desc, unit=unit):
        yield await f


async def fetch(session: aiohttp.ClientSession, url: str, **kwargs):
    err_count = 0
    while err_count < 5:
        try:
            async with FETCH_SEMAPHORE:
                async with session.get(url, **kwargs) as res:
                    if res.status == 429:
                        retry_after = int(res.headers["retry-after"] or '5')
                        asyncio.sleep(retry_after)
                        continue
                    elif res.status != 200:
                        raise Exception(f"{res.status} {res.reason}")
                    return await res.text()
        except SystemExit:
            raise
        except:
            err_count += 1
            asyncio.sleep(5)
            pass
    logError(f"Could not load page after 5 tries: {url}")
    raise SystemExit


def parse_recipe_links_page(text: str):
    tree = html.fromstring(text)
    rel_links = tree.xpath("//div/@data-ldst-href")
    links = map(str, rel_links)
    show_end = int(tree.xpath("//span[@class='show_end']/text()")[0])
    total = int(tree.xpath("//span[@class='total']/text()")[0])
    return links, show_end, total


async def fetch_recipe_links_page(session: aiohttp.ClientSession, cls: str, level_range: int, page: int):
    params = {
        "category2": CLASSES.index(cls),
        "category3": level_range,
        "page": page,
    }
    return parse_recipe_links_page(await fetch(session, RECIPE_LIST_URL, params=params))


async def fetch_recipe_links_range(session: aiohttp.ClientSession, cls: str, level_range: int):
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


async def fetch_recipe_links(session: aiohttp.ClientSession, cls: str):
    results = wait_with_progress(
        [fetch_recipe_links_range(session, cls, level_range) for level_range in range(0, NUM_LEVEL_RANGES)],
        desc=f"Fetching {cls} links",
        unit=""
    )

    links = []
    async for r in results:
        links.extend(r)

    return links


def make_recipe_url(lang: str, rel_link: str):
    return urlunparse(("http", LANG_HOSTS[lang], rel_link, "", "", ""))


async def fetch_recipe_pages(session: aiohttp.ClientSession, rel_link: str):
    pages = {}

    for lang in LANG_HOSTS:
        pages[lang] = html.fromstring(await fetch(session, make_recipe_url(lang, rel_link)))

    return pages


async def fetch_recipe(session: aiohttp.ClientSession, rel_link: str):
    pages = await fetch_recipe_pages(session, rel_link)

    tree = pages["en"]

    embed_code = tree.xpath("//div[@class='embed_code_txt']//div[contains(text(), 'db:recipe')]/text()")[0]
    match = EMBED_CODE_RE.match(embed_code)
    if match is None:
        raise Exception("recipe id not found")
    recipe_id = match.group(1)

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
    maxQuality = int(craft_data.xpath("li[span='Maximum Quality']/text()")[0])

    # Base level 51 recipes of difficulty 169 or 339 are adjusted to level 115
    # instead of the default 120 that other level 51 recipes are adjusted to.

    if ((base_level == 51 and (difficulty == 169 or difficulty == 339)) or
            (base_level == 61 and (difficulty == 1116 or difficulty == 558))):
        level -= 5
    if base_level == 60 and stars == 3 and difficulty == 1764:
        level += 10

    aspect = None

    craft_conditions = tree.xpath("//dl[@class='db-view__recipe__crafting_conditions']")[0]
    for characteristic in craft_conditions.xpath("dt[text()='Characteristics']/../dd/text()"):
        characteristic = characteristic.strip()
        match = ASPECT_RE.match(characteristic)
        if not match is None:
            aspect = match.group(1)

    recipe = {
        "id": recipe_id,
        "name": {},
        "baseLevel": base_level,
        "level": level,
        "difficulty": difficulty,
        "durability": durability,
        "maxQuality": maxQuality,
    }

    if stars:
        recipe["stars"] = stars

    if aspect:
        recipe["aspect"] = aspect

    for lang in LANG_HOSTS:
        tree = pages[lang]
        recipe["name"][lang] = str(tree.xpath("//h2[contains(@class,'db-view__item__text__name')]/text()")[0]).strip()

    return recipe


async def fetch_recipes(session: aiohttp.ClientSession, cls: str, links: list):
    recipes = wait_with_progress(
        [fetch_recipe(session, link) for link in links],
        desc=f"Fetching {cls} recipes",
        unit=""
    )

    return [r async for r in recipes]


async def fetch_class(session: aiohttp.ClientSession, additional_languages: dict, cls: str):
    links = await fetch_recipe_links(session, cls)
    recipes = await fetch_recipes(session, cls, links)
    recipes.sort(key=lambda r: (r['level'], r['name']['en']))
    for recipe in recipes:
        for lang in additional_languages.keys():
            names = additional_languages[lang]
            english_name = recipe['name']['en']
            recipe['name'][lang] = names.get(english_name) or english_name
    return recipes


async def scrape_to_file(session: aiohttp.ClientSession, additional_languages: dict, cls: str):
    recipes = await fetch_class(session, additional_languages, cls)
    with open("out/" + cls + ".json", mode="wt", encoding="utf-8") as db_file:
        json.dump(recipes, db_file, indent=2, sort_keys=True, ensure_ascii=False)


async def scrape_classes(session: aiohttp.ClientSession, additional_languages: dict):
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
    if args.lang_file:
        for f in args.lang_file:
            lang, path = f.split("=", 2)
            with open(path, mode="rt", encoding="utf-8") as fp:
                print(f"Loading additional language '{lang}' from: {path}")
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
