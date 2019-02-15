import json
import sys


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


def main():
    additional_languages = {}
    for arg in sys.argv[1:]:
        lang, path = arg.split("=", 2)
        with open(path, mode="rt", encoding="utf-8") as fp:
            print(f"Loading additional language '{lang}' from: {path}")
            additional_languages[lang] = json.load(fp)
    for cls in CLASSES:
        with open(f"out/{cls}.json", mode="rt", encoding="utf-8") as fp:
            recipes = json.load(fp)
        for recipe in recipes:
            for lang in additional_languages.keys():
                names = additional_languages[lang]
                english_name = recipe['name']['en']
                recipe['name'][lang] = names.get(english_name) or english_name
        with open(f"out/{cls}.json", mode="wt", encoding="utf-8") as db_file:
            json.dump(recipes, db_file, indent=2, sort_keys=True, ensure_ascii=False)


if __name__ == '__main__':
    main()
