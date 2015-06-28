import json
from urllib.parse import urljoin

import requests_cache
import lxml.html as html


BASE_URL = {
    "en": "http://na.finalfantasyxiv.com/lodestone/playguide/db/recipe/",
    "ja": "http://jp.finalfantasyxiv.com/lodestone/playguide/db/recipe/",
    "fr": "http://fr.finalfantasyxiv.com/lodestone/playguide/db/recipe/",
    "de": "http://de.finalfantasyxiv.com/lodestone/playguide/db/recipe/",
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

LEVEL_RANGE = ["{0}-{1}".format(start, start + 4) for start in range(1, 60, 5)]
NUM_LEVEL_RANGES = len(LEVEL_RANGE)

session = requests_cache.CachedSession()


def parse_recipe_links_page(base_url, r):
    tree = html.fromstring(r.text)
    rel_links = tree.xpath("//div/@data-ldst-href")
    links = [urljoin(base_url, rel_link) for rel_link in rel_links]
    show_end = int(tree.xpath("//span[@class='show_end']/text()")[0])
    total = int(tree.xpath("//span[@class='total']/text()")[0])
    return links, show_end, total


def fetch_recipe_links_page(cls, level_range, page):
    base_url = BASE_URL["en"]

    params = {
        "category2": CLASSES.index(cls),
        "category3": level_range,
        "page": page,
    }

    print("Fetching {0} {1} page {2}".format(cls, LEVEL_RANGE[level_range], page))

    return parse_recipe_links_page(base_url, session.get(base_url, params=params))

def fetch_recipe_links(cls):
    links = []

    for level_range in range(0, NUM_LEVEL_RANGES):
        page = 1
        while True:
            page_links, show_end, total = fetch_recipe_links_page(cls, level_range, page)
            links += page_links
            if show_end < total:
                page += 1
            else:
                break

    return links

def fetch_recipe(url):
    print("Fetching recipe: {0}".format(url))
    r = session.get(url)
    tree = html.fromstring(r.text)
    return {
        "name" : tree.xpath("//h2[contains(@class,'item_name')]/text()")[0],
        "level" : int(tree.xpath("//div[@class='recipe_level']/span/text()")[0]),
        "difficulty" : int(tree.xpath("//dl/dt[text()='Difficulty']/following-sibling::dd[1]/text()")[0]),
        "durability" : int(tree.xpath("//dl/dt[text()='Durability']/following-sibling::dd[1]/text()")[0]),
        "maxQuality" : int(tree.xpath("//dl/dt[text()='Maximum Quality']/following-sibling::dd[1]/text()")[0]),
    }

def fetch(cls):
    return [fetch_recipe(link) for link in fetch_recipe_links(cls)]

def scrape_to_file(cls):
    recipes = fetch(cls)
    with open("out/" + cls + ".json", "wt") as db_file:
        json.dump(recipes, db_file, indent="  ")
    print("Wrote {0} recipes for {1}".format(len(recipes), cls))

def main():
    for cls in CLASSES:
        scrape_to_file(cls)


if __name__ == '__main__':
    main()
