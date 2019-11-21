# Lodestone Recipe DB Scraper

This project provides a tool which scrapes recipe information from the Lodestone website's Eorzea Database. It extracts recipes for all classes, levels 1-60, including the English, German, French and Japanese names. Each class' recipes are written out to a separate JSON file in the order defined by the Lodestone's recipe listings.

# Pre-requisites

This project uses Python 3.4 (or newer) and describes its dependencies in a pip `requirements.txt` file. You can install all the packages required by running:

    pip install -r requirements.txt

If you are using Windows, you can first download the lxml extension (e.g. `lxml‑3.6.4‑cp35‑cp35m‑win_amd64.whl` for CPython 3.5 64-bit) from [here](http://www.lfd.uci.edu/~gohlke/pythonlibs/#lxml) and manually install using:

    pip install C:\path\to\downloaded\package.whl

And then install the remainder of the dependencies using the first `pip install` command.

If you would rather have pip compile the package, you will need to ensure that you have the correct version of Visual Studio installed (the Express edition will suffice), and run the first `pip install` command inside a "Visual Studio Command Prompt". Please see the [lxml installation instructions](http://lxml.de/installation.html) for further information.

Another alternative for Windows 10 is to use the _Windows Subsystem for Linux_. Once installed, in a Bash window you can use:

    sudo apt install python3 && sudo pip install -r requirements.txt

to install Python and all the dependencies, and then run Python as described below.

# Usage

Run `main.py` with the following arguments:

    python main.py -l cn=items_cn.json -r all
    
It will output its progress to stdout and generate `json` files in the `out` subdirectory.

The `-l` option includes names in languages not supported by the Lodestone, e.g. Chinese. The option must be provided as `LANG=FILE`, where `LANG` is the two-letter code identifying the language and `FILE` is the path to the file containing the translations. The file must contain a JSON object with the English recipe names as the keys and the translated names as the values. You can specify the `-l` option multiple times to add multiple languages.

You can specify a class e.g. `alchemist` instead of `all` in the `-r` option. The `-r` option can be specified more than once to collect multiple classes.

Alternatively, you can run `add_other_lang.py` with one or more `LANG=FILE` arguments to update an existing set of output files with translations for additional languages, without needing to re-scrape.

    python add_other_lang.py cn=items_cn.json ko=items_ko.json
