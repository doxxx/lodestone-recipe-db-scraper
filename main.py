import json
from urllib.parse import urlunparse
from concurrent.futures import ThreadPoolExecutor

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
    60: [ 90, 100 ], # 150, 160
}

LEVEL_RANGE = ["{0}-{1}".format(start, start + 4) for start in range(1, 60, 5)]
NUM_LEVEL_RANGES = len(LEVEL_RANGE)

session = requests_cache.CachedSession()
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

    base_level = int(tree.xpath("//div[@class='recipe_level']/span/text()")[0])
    level_adjustment = 0
    if base_level in LEVEL_DIFF:
        stars = len(tree.xpath("//div[@class='recipe_level']/span[contains(@class, 'star')]"))
        level_adjustment = LEVEL_DIFF[base_level][stars]
    level = base_level + level_adjustment

    recipe = {
        "name" : {},
        "level" : level,
        "difficulty" : int(tree.xpath("//dl/dt[text()='Difficulty']/following-sibling::dd[1]/text()")[0]),
        "durability" : int(tree.xpath("//dl/dt[text()='Durability']/following-sibling::dd[1]/text()")[0]),
        "maxQuality" : int(tree.xpath("//dl/dt[text()='Maximum Quality']/following-sibling::dd[1]/text()")[0]),
    }

    for lang in LANG_HOSTS:
        tree = html.fromstring(pages[lang].result().text)
        recipe["name"][lang] = str(tree.xpath("//h2[contains(@class,'item_name')]/text()")[0])

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
