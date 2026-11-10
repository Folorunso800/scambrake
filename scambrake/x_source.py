"""Optional live source: recent public posts from the X API v2 (read-only, needs your own X_BEARER_TOKEN).
The demo does NOT need this: it replays fixtures/posts.json. Not exercised against the live X API in the
hackathon build (no token was used); the request/response handling is covered by a stubbed test."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

SEARCH = "https://api.x.com/2/tweets/search/recent"


def live_posts(query, token=None, max_results=50, opener=urllib.request.urlopen):
    token = token or os.environ.get("X_BEARER_TOKEN")
    if not token:
        raise SystemExit("set X_BEARER_TOKEN to read live posts (or use the replay fixtures)")
    params = {"query": query + " -is:retweet", "max_results": str(max_results), "tweet.fields": "created_at,author_id",
              "expansions": "author_id", "user.fields": "username"}
    req = urllib.request.Request(SEARCH + "?" + urllib.parse.urlencode(params), headers={"Authorization": f"Bearer {token}"})
    try:
        with opener(req, timeout=30) as r:
            j = json.load(r)
    except (urllib.error.URLError, OSError) as e:
        print(f"X API unavailable: {e}")
        return []
    users = {u["id"]: u["username"] for u in j.get("includes", {}).get("users", [])}
    posts = []
    for p in j.get("data", []):
        h = users.get(p["author_id"], p["author_id"])
        posts.append({"id": p["id"], "username": h, "created_at": p["created_at"], "text": p["text"],
                      "url": f"https://x.com/{h}/status/{p['id']}"})
    return posts
