import signal
import argparse
import json
import re
import sys
from typing import Mapping, Sequence
from urllib.parse import urlunparse

import lxml.html as html
import asyncio
import aiohttp
import tqdm

# type definitions
LanguageMapping = Mapping[str,Mapping[str,str]]

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
    80: [ 340, 350 ], # 420, 430
}

MAX_LEVEL = 80
LEVEL_RANGES = ["{0}-{1}".format(start, start + 4) for start in range(1, MAX_LEVEL, 5)]
NUM_LEVEL_RANGES = len(LEVEL_RANGES)
NUM_ADDITIONAL_CATEGORIES = 6
LINK_CATEGORIES = ['%d' % (level_range,) for level_range in range(0, NUM_LEVEL_RANGES)] + \
                  ['c%d' % (cat,) for cat in range(1, NUM_ADDITIONAL_CATEGORIES+1)]

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
                    return await res.text()
        except SystemExit:
            raise
        except:
            err_count += 1
            await asyncio.sleep(5)
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


async def fetch_recipe_links_page(session: aiohttp.ClientSession, cls: str, category: str, page: int):
    params = {
        "category2": CLASSES.index(cls),
        "category3": category,
        "page": page,
    }
    return parse_recipe_links_page(await fetch(session, RECIPE_LIST_URL, params=params))


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
        [fetch_recipe_links_range(session, cls, category) for category in LINK_CATEGORIES],
        desc=f"Fetching {cls.capitalize()} links",
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


async def scrape_to_file(session: aiohttp.ClientSession, additional_languages: LanguageMapping, cls: str):
    recipes = await fetch_class(session, additional_languages, cls)
    with open(f"out/{cls}.json", mode="wt", encoding="utf-8") as db_file:
        json.dump(recipes, db_file, indent=2, sort_keys=True, ensure_ascii=False)


async def scrape_classes(session: aiohttp.ClientSession, classes: Sequence[str], additional_languages: LanguageMapping):
    for cls in classes:
        await scrape_to_file(session, additional_languages, cls)


def load_additional_languages(specs: Sequence[str]) -> LanguageMapping:
    additional_languages = {}
    for s in specs:
        lang, path = s.split("=", 2)
        with open(path, mode="rt", encoding="utf-8") as fp:
            print(f"Loading additional language '{lang}' from: {path}")
            additional_languages[lang] = json.load(fp)
    return additional_languages


async def async_main(args):
    global FETCH_SEMAPHORE
    FETCH_SEMAPHORE = asyncio.Semaphore(args.concurrency)
    session = aiohttp.ClientSession()

    if args.lang_file:
        additional_languages = load_additional_languages(args.lang_file)
    else:
        additional_languages = {}

    try:
        if args.recipes:
            classes = [cls.lower() for cls in args.recipes]
            if "all" in classes:
                classes = CLASSES
            await scrape_classes(session, classes, additional_languages)
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
        choices=CLASSES,
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
