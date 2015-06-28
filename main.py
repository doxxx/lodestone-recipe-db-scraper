import recipe_list
import json
from concurrent.futures import ThreadPoolExecutor

def fetch(params):
    cls, level_range = params
    print("Fetching {0}:{1}...".format(cls, level_range))
    links = recipe_list.fetch_list("en", cls, level_range)
    return {
        "class": cls,
        "recipes": [recipe_list.fetch_recipe(link) for link in links]
    }

def add_recipe_metadata(recipe, metadata):
    r = recipe.copy()
    r.update(metadata)
    return r

def main():
    db_files = {cls:open("out/" + cls + ".json", "wt") for cls in recipe_list.CLASSES}

    with ThreadPoolExecutor(max_workers=4) as ex:
        for cls in recipe_list.CLASSES:
            with db_files[cls] as db_file:
                #metadata = { "cls": cls }
                combined_results = []
                params = [(cls, level_range) for level_range in range(0, 12)]
                for results in ex.map(fetch, params):
                    cls = results["class"]
                    recipes = results["recipes"]
                    print("Adding {0} results for {1}".format(len(recipes), cls))
                    #recipes = [add_recipe_metadata(r, metadata) for r in recipes]
                    combined_results += recipes
                json.dump(combined_results, db_file, indent="  ")

if __name__ == '__main__':
    main()
