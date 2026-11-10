"""Scan crypto-Twitter style posts for scam patterns. Pure rules, no AI, no network, so the result
is the same on every machine and every finding can be explained.

Finds: seed-phrase asks, 'connect wallet to claim' drainers, token-approval tricks, send-X-get-more
giveaways, fake 'official' links (a brand name inside a domain that is not the brand's), pump hype,
and text that tries to give orders to AI agents (prompt injection). Also pulls out the wallet
addresses a post is pushing, so they can be matched against a receiver later."""
import re
from urllib.parse import urlparse

# brand -> domains that really belong to it (a short list is enough for the demo; it is data, edit it)
OFFICIAL = {
    "near": {"near.org", "near.ai", "nearblocks.io", "nearprotocol.com", "near.com", "nearhackathon.com", "nearbuilders.org", "near-intents.org"},
    "rhea": {"rhea.finance"},
    "ref": {"ref.finance"},
    "meteor": {"meteorwallet.app"},
    "binance": {"binance.com", "binance.us"},
    "coinbase": {"coinbase.com"},
    "metamask": {"metamask.io"},
    "phantom": {"phantom.app", "phantom.com"},
    "uniswap": {"uniswap.org"},
    "opensea": {"opensea.io"},
    "ledger": {"ledger.com"},
}
SHORTENERS = {"bit.ly", "tinyurl.com", "cutt.ly", "t.ly", "rb.gy", "is.gd", "shorturl.at"}

URL_RE = re.compile(r"(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})(?:/[^\s]*)?", re.I)
NEAR_ADDR_RE = re.compile(r"\b((?:[a-z0-9]+[-_])*[a-z0-9]+(?:\.(?:[a-z0-9]+[-_])*[a-z0-9]+)*\.(?:near|testnet))\b")
IMPLICIT_RE = re.compile(r"\b([0-9a-f]{64})\b")
EVM_RE = re.compile(r"\b(0x[0-9a-fA-F]{40})\b")

# (category, weight, regex, explanation)
RULES = [
    ("seed_phrase_ask", 60, re.compile(r"(seed phrase|recovery phrase|secret phrase|12[- ]word|24[- ]word|private key)", re.I),
     "asks for a seed phrase or private key"),
    ("drainer_connect", 40, re.compile(r"(connect (?:your )?wallet|verify (?:your )?wallet|sync (?:your )?wallet|validate (?:your )?wallet|wallet (?:rectif|sync|validat))", re.I),
     "asks you to connect or 'verify' a wallet on a link"),
    ("approval_trick", 40, re.compile(r"(setApprovalForAll|increaseAllowance|approve (?:unlimited|all|max)|unlimited approval|sign (?:this|the) (?:message|permit) to (?:claim|receive))", re.I),
     "asks for a token approval or permit signature"),
    ("giveaway_double", 45, re.compile(r"(send (?:\d+\.?\d*\s*)?[a-z]{2,6} (?:and )?(?:get|receive|win)|double your|2x your|(?:first|next) \d+ (?:senders|wallets) (?:get|receive))", re.I),
     "send-some-get-more giveaway"),
    ("airdrop_claim", 25, re.compile(r"(claim (?:your )?(?:free )?(?:[a-z]+ )?(?:airdrop|rewards?|tokens?)|airdrop (?:is )?live|eligible (?:wallets?|users?)|free airdrop)", re.I),
     "airdrop claim bait"),
    ("urgency", 10, re.compile(r"(last chance|hurry|only \d+ (?:hours?|minutes?|spots?)|expires? (?:in|today|soon)|act now|limited time)", re.I),
     "pressure to act fast"),
    ("pump_hype", 15, re.compile(r"(100x|1000x|guaranteed (?:profit|returns?|gains?)|can't lose|stealth launch|ape (?:in )?now|next gem|financial freedom|presale (?:live|ends))", re.I),
     "guaranteed-profit or pump language"),
    ("agent_hijack", 60, re.compile(r"(ignore (?:all |any )?(?:previous|prior|above) (?:instructions|rules)|you are now|new instructions:|system (?:prompt|override)|(?:ai|trading) agents?[:,]? (?:must|should|please)? ?(?:send|transfer|pay)|as an ai (?:agent|assistant)[, ]+(?:send|transfer|pay))", re.I),
     "text that tries to give orders to an AI agent (prompt injection)"),
]


def _host(h):
    h = h.lower().strip(".")
    return h[4:] if h.startswith("www.") else h


def _is_official(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


def extract_links(text):
    out = []
    for m in URL_RE.finditer(text):
        h = _host(m.group(1))
        # skip things that are really NEAR account names like alice.near or bob.testnet
        if h.endswith((".near", ".testnet")) and "/" not in m.group(0):
            continue
        if h not in out:
            out.append(h)
    return out


SUSPICIOUS_WORDS = {"claim", "airdrop", "wallet", "verify", "official", "support", "app", "swap", "pro", "secure",
                    "login", "connect", "reward", "rewards", "drop", "event", "mint", "token", "protocol",
                    "finance", "sync", "validate", "bonus", "gift", "giveaway", "dao", "labs", "foundation", "xyz"}
_LEET = str.maketrans("340", "eao")


def fake_official_links(text):
    """Hosts that use a brand name but do not belong to that brand. -> [(host, brand)]"""
    bad = []
    for h in extract_links(text):
        if any(_is_official(h, o) for o in OFFICIAL.values()):
            continue
        for brand in OFFICIAL:
            hit = False
            for label in re.split(r"[.\-]", h)[:-1]:  # ignore the TLD
                label = label.translate(_LEET)
                if label == brand:
                    hit = True
                elif brand in label:
                    rest = label.replace(brand, "", 1)
                    hit = rest in SUSPICIOUS_WORDS
                if hit:
                    break
            if hit:
                bad.append((h, brand))
                break
    return bad


def extract_addresses(text):
    near = [a for a in NEAR_ADDR_RE.findall(text.lower()) if a not in ("near", "testnet")]
    return {
        "near": sorted(set(near)),
        "implicit": sorted(set(IMPLICIT_RE.findall(text.lower()))),
        "evm": sorted(set(EVM_RE.findall(text))),
    }


def scan_post(text):
    """-> {'score': 0-100, 'verdict': 'ok'|'suspicious'|'scam', 'categories': [...], 'reasons': [...], 'links', 'addresses'}"""
    findings = []
    score = 0
    for cat, w, rx, why in RULES:
        m = rx.search(text)
        if m:
            findings.append({"category": cat, "why": why, "match": m.group(0)[:60], "weight": w})
            score += w
    links = extract_links(text)
    fakes = fake_official_links(text)
    for host, brand in fakes:
        findings.append({"category": "fake_official_link", "why": f"link {host} looks like '{brand}' but is not an official {brand} domain", "match": host, "weight": 45})
        score += 45
    for h in links:
        if h in SHORTENERS:
            findings.append({"category": "shortened_link", "why": f"hides its destination behind {h}", "match": h, "weight": 10})
            score += 10
    addrs = extract_addresses(text)
    score = min(100, score)
    verdict = "scam" if score >= 60 else "suspicious" if score >= 30 else "ok"
    return {"score": score, "verdict": verdict, "categories": sorted({f["category"] for f in findings}),
            "findings": findings, "links": links, "addresses": addrs}


def scan_posts(posts):
    """posts: [{'id','username','text','url',...}] -> list of results (with the post attached), and intel by address."""
    results, intel = [], {}
    for p in posts:
        r = scan_post(p["text"])
        r["post"] = {k: p.get(k) for k in ("id", "username", "url", "created_at")}
        results.append(r)
        if r["verdict"] in ("scam", "suspicious"):
            for kind in ("near", "implicit", "evm"):
                for a in r["addresses"][kind]:
                    e = intel.setdefault(a, {"address": a, "posts": [], "categories": set(), "max_score": 0})
                    e["posts"].append(r["post"]["url"] or r["post"]["id"])
                    e["categories"].update(r["categories"])
                    e["max_score"] = max(e["max_score"], r["score"])
    for e in intel.values():
        e["categories"] = sorted(e["categories"])
    return results, intel
