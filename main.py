#!/usr/bin/env python3

"""
Ideas and implementation borrowed from:
https://github.com/apoorvalal/bsky_paperbot/blob/master/paperbot.py
Thanks!

"""

import json
import random
import re
import time
from typing import Dict
from atproto import Client, client_utils

import feedparser

urls = {
    "American Sociological Review (AoP)": "https://journals.sagepub.com/action/showFeed?ui=0&mi=ehikzz&ai=2b4&jc=asra&type=axatoc&feed=rss",
    "American Sociological Review": "https://journals.sagepub.com/action/showFeed?ui=0&mi=ehikzz&ai=2b4&jc=asra&type=etoc&feed=rss",
    "Annual Review of Sociology": "https://www.annualreviews.org/rss/content/journals/soc/latestarticles?fmt=rss",
    "Socius": "https://journals.sagepub.com/action/showFeed?ui=0&mi=ehikzz&ai=2b4&jc=srda&type=etoc&feed=rss",
    "Social Forces": "https://academic.oup.com/rss/site_5513/3374.xml",
    # AJS not working atm, because they don't include abstracts in their RSS-feed
    "American Journal of Sociology": "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=ajs",
    "SocArXiv": "https://share.osf.io/api/v2/feeds/atom/?elasticQuery=%7B%22bool%22%3A%7B%22must%22%3A%7B%22query_string%22%3A%7B%22query%22%3A%22*%22%7D%7D%2C%22filter%22%3A%5B%7B%22term%22%3A%7B%22sources%22%3A%22SocArXiv%22%7D%7D%5D%7D%7D",
    "Sociological Science": "https://sociologicalscience.com/category/articles/feed/",
    "Sociological Methods and Research": "https://journals.sagepub.com/action/showFeed?ui=0&mi=ehikzz&ai=2b4&jc=smra&type=etoc&feed=rss",
    "European Sociological Review": "https://academic.oup.com/rss/site_5160/advanceAccess_3023.xml",
}


def is_valid_paper(title, description):
    """Check if entry is a valid paper, not a review or other entry"""
    title_lower = title.lower()
    return all(
        [
            len(title) >= 50,
            len(description) >= 50,
            not title_lower.startswith("review"),
            not title_lower.startswith("corrigendum"),
        ]
    )


def filter_results(results):
    filtered_results = {}
    for k, v in results.items():
        if is_valid_paper(v["title"], v["description"]):
            journal = v.get("journal", "")
            filtered_results[k] = {
                **v,
                "title": v["title"],
                "description": clean_abstract(v["description"], journal),
            }
    return filtered_results


def clean_abstract(text, journal):
    text = re.sub(r"<[^>]+>", "", text)  # Removes symbols
    text = re.sub(
        r"\b(abstract)(\w*)", r"\2", text, flags=re.I
    )  # Removes 'Abstract' from text

    if journal in [
        "Socius",
        "American Sociological Review (AoP)",
        "American Sociological Review",
        "Sociological Methodology",
        "Sociological Methods and Research",
    ]:
        text = re.sub(r"^.*?\.", "", text, 1)  # Removes everything up to first "."

    elif journal == "Sociological Science":
        start = text.find("Abstract")
        end = text.rfind("Close")
        text = text[start + len("Abstract") : end].strip()

    text = text.strip()
    return text


class PosterBot:
    def __init__(self, handle: str, password: str):
        self.client = Client()
        self.client.login(handle, password)

    def create_post(self, title: str, link: str, description: str):
        """Create a Bluesky post with paper details"""
        # Reserve characters for link and emoji
        post_text = f"{title} {description}"[:280] + "\n #sociology "
        post_builder = client_utils.TextBuilder().text(post_text).link("link", link)
        self.client.send_post(post_builder)

    def get_rss_feed(self, urls=urls) -> Dict:
        """Fetch and parse all RSS feeds."""
        all_entries = {}
        for journal, url in urls.items():
            feed = feedparser.parse(url)
            for entry in feed.entries:
                link = entry.link.strip()
                all_entries[link] = {
                    "title": entry.title.strip(),
                    "link": entry.link.strip(),
                    "description": (
                        entry.description.split("Abstract:", 1)[1].strip()
                        if "Abstract:" in entry.description
                        else entry.description.strip()
                    ),
                }
        return filter_results(all_entries)

    def update_archive(self, feed: Dict, archive_file: str = "combined.json") -> tuple:
        """Update archive with new entries"""
        try:
            with open(archive_file, "r") as f:
                archive = json.load(f)
        except FileNotFoundError:
            archive = {}

        new_archive = archive.copy()
        for k, v in feed.items():
            if k not in archive:
                new_archive[k] = v

        if len(new_archive) > len(archive):
            with open(archive_file, "w") as f:
                json.dump(new_archive, f)

        return feed, archive

    def run(self):
        """Main bot loop"""
        feed, archive = self.update_archive(self.get_rss_feed())
        new_posts = 0

        # Post new papers
        for k, v in feed.items():
            if k not in archive:
                self.create_post(v["title"], v["link"], v["description"])
                time.sleep(random.randint(60, 300))
                new_posts += 1

        # Post random paper if no new ones found
        if new_posts == 0 and len(archive) > 2:
            paper = random.choice(list(archive.values()))
            # if paper contains key authors - back-compat
            self.create_post(paper["title"], paper["link"], paper["description"])
            time.sleep(random.randint(30, 60))


def main():
    import os

    bot = PosterBot(os.environ["BSKYBOT"], os.environ["BSKYPWD"])
    bot.run()


# %%
if __name__ == "__main__":
    main()
# %%
