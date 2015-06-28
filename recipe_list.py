import requests
import requests_cache
import lxml.html as html
from urllib.parse import urljoin

requests_cache.install_cache()

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

session = requests.Session()

def fetch_list(lang, cls, level_range):
    base_url = BASE_URL[lang]

    params = {
        "category2": CLASSES.index(cls),
        "category3": level_range,
        "page": 1,
    }

    links = []

    while True:
        r = session.get(base_url, params=params)
        tree = html.fromstring(r.text)
        rel_links = tree.xpath("//div/@data-ldst-href")
        links += [urljoin(base_url, rel_link) for rel_link in rel_links]
        show_end = int(tree.xpath("//span[@class='show_end']/text()")[0])
        total = int(tree.xpath("//span[@class='total']/text()")[0])
        if show_end < total:
            params["page"] += 1
        else:
            break

    return links

def fetch_recipe(url):
    r = session.get(url)
    tree = html.fromstring(r.text)
    return {
        "name" : tree.xpath("//h2[contains(@class,'item_name')]/text()")[0],
        "level" : int(tree.xpath("//div[@class='recipe_level']/span/text()")[0]),
        "difficulty" : int(tree.xpath("//dl/dt[text()='Difficulty']/following-sibling::dd[1]/text()")[0]),
        "durability" : int(tree.xpath("//dl/dt[text()='Durability']/following-sibling::dd[1]/text()")[0]),
        "maxQuality" : int(tree.xpath("//dl/dt[text()='Maximum Quality']/following-sibling::dd[1]/text()")[0]),
    }
