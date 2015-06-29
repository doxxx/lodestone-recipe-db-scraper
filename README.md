# Lodestone Recipe DB Scraper

This project provides a tool which scrapes recipe information from the Lodestone website's Eorzea Database. It extracts recipes for all classes, levels 1-60, including the English, German, French and Japanese names. Each class' recipes are written out to a separate JSON file in the order defined by the Lodestone's recipe listings.

# Pre-requisites

This project uses Python 3.4 and describes its dependencies in a pip `requirements.txt` file. You can install all the packages required by running:

    pip install -r requirements.txt

If you are using Windows, you will need to ensure that you have Visual Studio 2010 installed (the [Express edition](http://go.microsoft.com/?linkid=9709949) will suffice), and run the `pip` command inside a "Visual Studio Command Prompt". Please see the [lxml installation instructions](http://lxml.de/installation.html) for further information.

# Usage

Simply run `main.py`:

    python main.py
    
It will output its progress to stdout and generate `json` files in the `out` subdirectory. The Lodestone web pages are cached in a local sqlite database, so subsequent runs will go much faster. The database will get quite large, ~1.6GB at my last run. To force it to redownload the web pages, simply delete the `cache.sqlite` file.
