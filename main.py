#!/usr/bin/env python3

"""
Ideas and implementation borrowed from:
https://github.com/apoorvalal/bsky_paperbot/blob/master/paperbot.py
Thanks!

"""
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List

import feedparser
import requests


def bsky_login_session(pds_url: str, handle: str, password: str) -> Dict:
    """login to blueksy

    Args:
        pds_url (str): bsky platform (default for now)
        handle (str): username
        password (str): app password

    Returns:
        Dict: json blob with login
    """
    resp = requests.post(
        pds_url + "/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": password},
    )
    resp.raise_for_status()
    return resp.json()


def parse_urls(text: str) -> List[Dict]:
    """parse URLs in string blob

    Args:
        text (str): string

    Returns:
        List[Dict]: span of url
    """
    spans = []
    # partial/naive URL regex based on: https://stackoverflow.com/a/3809435
    # tweaked to disallow some training punctuation
    url_regex = rb"[$|\W](https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*[-a-zA-Z0-9@%_\+~#//=])?)"
    text_bytes = text.encode("UTF-8")
    for m in re.finditer(url_regex, text_bytes):
        spans.append(
            {
                "start": m.start(1),
                "end": m.end(1),
                "url": m.group(1).decode("UTF-8"),
            }
        )
    return spans


def parse_facets(text: str) -> List[Dict]:
    """
    parses post text and returns a list of app.bsky.richtext.facet objects for any URLs (https://example.com)
    """
    facets = []
    for u in parse_urls(text):
        facets.append(
            {
                "index": {
                    "byteStart": u["start"],
                    "byteEnd": u["end"],
                },
                "features": [
                    {
                        "$type": "app.bsky.richtext.facet#link",
                        # NOTE: URI ("I") not URL ("L")
                        "uri": u["url"],
                    }
                ],
            }
        )
    return facets


def create_post(
    text: str,
    pds_url: str = "https://bsky.social",
    handle: str = os.environ["BSKYBOT"],
    password: str = os.environ["BSKYPWD"],
):
    """post on bluesky

    Args:
        text (str): text
        pds_url (str, optional): bsky Defaults to "https://bsky.social".
        handle (_type_, optional):  Defaults to os.environ["BSKYBOT"]. Set this environmental variable in your dotfile (bashrc/zshrc).
        password (_type_, optional): _description_. Defaults to os.environ["BSKYPWD"].
    """
    session = bsky_login_session(pds_url, handle, password)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    # these are the required fields which every post must include
    post = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": now,
    }

    # parse out mentions and URLs as "facets"
    if len(text) > 0:
        facets = parse_facets(post["text"])
        if facets:
            post["facets"] = facets

    resp = requests.post(
        pds_url + "/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": "Bearer " + session["accessJwt"]},
        json={
            "repo": session["did"],
            "collection": "app.bsky.feed.post",
            "record": post,
        },
    )
    print("createRecord response:", file=sys.stderr)
    print(json.dumps(resp.json(), indent=2))
    resp.raise_for_status()


# RSS feeds
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
}


def get_rss_feed(urls):
    """Fetch the rss-feeds"""
    results = {}
    for k, v in urls.items():
        f = feedparser.parse(v)
        results.update(
            {
                entry.get("link", ""): {
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "description": entry.get("description", ""),
                    "journal": k,
                }
                for entry in f.entries
            }
        )
    return results


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


def clean_abstract(text, journal):
    text = re.sub(r"<[^>]+>", "", text)

    if journal in [
        "Socius",
        "American Sociological Review (AoP)",
        "American Sociological Review",
    ]:
        text = re.sub(r"^.*?\.", "", text, 1)  # Removes everything up to first "."

    elif journal == "Sociological Science":
        start = text.find("Abstract")
        end = text.rfind("Close")
        text[start + len("Abstract") : end].strip()

    text = text.strip()
    return text


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


def write_json_from_rss(urls=urls, filename="combined.json"):
    results = get_rss_feed(urls)
    filtered_results = filter_results(results)

    try:
        with open(filename, "r") as f:
            archive = json.load(f)
    except FileNotFoundError:
        archive = {}

    new_archive = archive.copy()

    # Append new items
    for link, item_data in filtered_results.items():
        if link not in archive:
            new_archive[link] = item_data

    if len(new_archive) > len(archive):
        with open(filename, "w") as f:
            json.dump(new_archive, f, indent=2)
        print(f"{filename} updated")

    return filtered_results, archive


# %%
def main():
    pull, archive = write_json_from_rss()
    ######################################################################
    # stats
    ######################################################################
    new_posts = 0

    # Append new data to existing data
    for k, v in pull.items():
        if k not in archive:  # if not already posted
            post_str = (
                f"{v['title']}\n{v['link']}\n{''.join(v['description'])}"[:288]
                + "\n #sociology"
            )
            create_post(post_str.replace("\n", " "))
            time.sleep(random.randint(60, 300))
            archive[k] = v
            new_posts += 1
    if new_posts == 0 & (len(archive) > 2):
        print("No new papers found; posting random paper from archive")
        random_paper = random.choice(list(archive.values()))
        post_str = (
            f"{random_paper['title']}\n{random_paper['link']}\n{''.join(random_paper['description'])}"[
                :288
            ]
            + "\n #sociology"
        )
        create_post(post_str.replace("\n", " "))
        time.sleep(random.randint(30, 60))


# %%
if __name__ == "__main__":
    main()
# %%
