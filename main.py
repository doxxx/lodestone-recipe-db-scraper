import json
from urllib.parse import urlunparse
from concurrent.futures import ThreadPoolExecutor
import re

import requests_cache
import lxml.html as html


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
    60: [ 90, 100, 110, 120 ], # 150, 160, 170, 180
}

LEVEL_RANGE = ["{0}-{1}".format(start, start + 4) for start in range(1, 60, 5)]
NUM_LEVEL_RANGES = len(LEVEL_RANGE)

ASPECT_RE = re.compile("Aspect: (.+)")

session = requests_cache.CachedSession(expire_after=3600)
executor = ThreadPoolExecutor(max_workers=4)


def parse_recipe_links_page(r):
    tree = html.fromstring(r.text)
    rel_links = tree.xpath("//div/@data-ldst-href")
    links = map(str, rel_links)
    show_end = int(tree.xpath("//span[@class='show_end']/text()")[0])
    total = int(tree.xpath("//span[@class='total']/text()")[0])
    return links, show_end, total

def fetch_recipe_links_page(cls, level_range, page):
    params = {
        "category2": CLASSES.index(cls),
        "category3": level_range,
        "page": page,
    }

    return parse_recipe_links_page(session.get(RECIPE_LIST_URL, params=params))

def fetch_recipe_links(cls):
    links = []

    for level_range in range(0, NUM_LEVEL_RANGES):
        page = 1
        while True:
            print("\rFetching {0} links... {1} page {2}".format(cls, LEVEL_RANGE[level_range], page), end="")
            page_links, show_end, total = fetch_recipe_links_page(cls, level_range, page)
            links += page_links
            if show_end < total:
                page += 1
            else:
                break

    print("\rFetching {0} links... done.".format(cls))

    return links


def make_recipe_url(lang, rel_link):
    return urlunparse(("http", LANG_HOSTS[lang], rel_link, "", "", ""))

def fetch_recipe(rel_link):
    pages = {lang: executor.submit(session.get, make_recipe_url(lang, rel_link)) for lang in LANG_HOSTS}

    tree = html.fromstring(pages["en"].result().text)

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
        tree = html.fromstring(pages[lang].result().text)
        recipe["name"][lang] = str(tree.xpath("//h2[contains(@class,'db-view__item__text__name')]/text()")[0]).strip()

    return recipe

def fetch(cls):
    recipes = []
    links = fetch_recipe_links(cls)
    for i in range(0, len(links)):
        print("\rFetching {0} recipe... {1} of {2}".format(cls, i+1, len(links)), end="")
        recipes.append(fetch_recipe(links[i]))
    print("\rFetching {0} recipes... done.".format(cls))
    recipes.sort(key=lambda r: (r['level'], r['name']['en']))
    return recipes

def scrape_to_file(cls):
    recipes = fetch(cls)
    with open("out/" + cls + ".json", "wt") as db_file:
        json.dump(recipes, db_file, indent=2, sort_keys=True)
    print("Wrote {0} recipes for {1}".format(len(recipes), cls))

def main():
    for cls in CLASSES:
        scrape_to_file(cls)
    executor.shutdown()


if __name__ == '__main__':
    main()
