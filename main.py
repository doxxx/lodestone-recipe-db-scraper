import json
from urllib.parse import urljoin, urlparse, urlunparse
from concurrent.futures import ThreadPoolExecutor

import requests_cache
import lxml.html as html


BASE_URL = "http://na.finalfantasyxiv.com/lodestone/playguide/db/recipe/"

LANGUAGES = {
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

LEVEL_RANGE = ["{0}-{1}".format(start, start + 4) for start in range(1, 60, 5)]
NUM_LEVEL_RANGES = len(LEVEL_RANGE)

session = requests_cache.CachedSession()
executor = ThreadPoolExecutor(max_workers=4)

def parse_recipe_links_page(base_url, r):
    tree = html.fromstring(r.text)
    rel_links = tree.xpath("//div/@data-ldst-href")
    links = [urljoin(base_url, str(rel_link)) for rel_link in rel_links]
    show_end = int(tree.xpath("//span[@class='show_end']/text()")[0])
    total = int(tree.xpath("//span[@class='total']/text()")[0])
    return links, show_end, total


def fetch_recipe_links_page(cls, level_range, page):
    params = {
        "category2": CLASSES.index(cls),
        "category3": level_range,
        "page": page,
    }

    return parse_recipe_links_page(BASE_URL, session.get(BASE_URL, params=params))

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


def switch_url_host(url, host):
    parsed_url = urlparse(url)
    return urlunparse((parsed_url.scheme, host, parsed_url.path, parsed_url.params, parsed_url.query, parsed_url.fragment))

def fetch_recipe(url):
    pages = {"en": executor.submit(session.get, url)}

    for lang in LANGUAGES:
        url = switch_url_host(url, LANGUAGES[lang])
        pages[lang] = executor.submit(session.get, url)

    tree = html.fromstring(pages["en"].result().text)
    recipe = {
        "name" : { "en": str(tree.xpath("//h2[contains(@class,'item_name')]/text()")[0]) },
        "level" : int(tree.xpath("//div[@class='recipe_level']/span/text()")[0]),
        "difficulty" : int(tree.xpath("//dl/dt[text()='Difficulty']/following-sibling::dd[1]/text()")[0]),
        "durability" : int(tree.xpath("//dl/dt[text()='Durability']/following-sibling::dd[1]/text()")[0]),
        "maxQuality" : int(tree.xpath("//dl/dt[text()='Maximum Quality']/following-sibling::dd[1]/text()")[0]),
    }

    for lang in LANGUAGES:
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
    return recipes

def scrape_to_file(cls):
    recipes = fetch(cls)
    with open("out/" + cls + ".json", "wt") as db_file:
        json.dump(recipes, db_file, indent="  ")
    print("Wrote {0} recipes for {1}".format(len(recipes), cls))

def main():
    for cls in CLASSES:
        scrape_to_file(cls)
    executor.shutdown()

if __name__ == '__main__':
    main()
