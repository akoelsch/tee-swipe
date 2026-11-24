#!/usr/bin/env python3
"""Collect on-sale T-shirts in size M from skate shops. Writes shirts.json.

Most shops run Shopify, which serves a public feed at /products.json.
Shops that are not Shopify (or that block bots) fail and are listed in
"stores_failed" in the output. The run continues without them.

Usage: python collect.py [output.json]
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

# Store name | base URL. Add or remove lines as you like.
STORES = """
Cowtown | https://www.cowtownskateboards.com
Garage Skateshop | https://garageskateshop.com
Atlas SF | https://shop.atlasskateboarding.com
FTC SF | https://ftcsf.com
Furnace | https://www.furnaceskate.com
Impact | https://www.impactskateshop.com
Innercity | https://innercityskate.com
PLA Skate | https://www.plaskateboarding.com
Pharmacy | https://pharmacyboardshop.com
Rose Street | https://rosestreetskateshop.com
Slappy's Garage | https://slappys.online
Family Sports | https://shopatfamily.com
303 Boards | https://www.303boards.com
Plush | https://plush-tek.com
Commonwealth | https://commonwealth-ftgg.com
Andrew | https://andrewdowntown.com
APB | https://www.apbstore.com
Plus | https://plusskateshop.com
Drifthouse | https://www.drifthouse.com
Home | https://www.homeskateshop.com
Humidity | https://humiditynola.com
Mocean | https://moceanskateboards.com
Vu | https://vuskateboardshop.com
Embark | https://embarkskateshop.com
Concepts | https://cncpts.com
Olympia | https://olympiaskateshop.com
Premier | https://thepremierstore.com
Theory | https://theoryskate.com
Familia | https://familiaskate.com
Coureur Goods | https://coureurgoods.com
NJ Skateshop | https://njskateshop.com
Blue Flowers | https://blueflowers.com
Extra Butter | https://extrabutterny.com
Sesinko | https://sesinko.com
This Skateshop | https://thisskateshop.com
Manifest | https://www.manifestskateshop.com
Stardust | https://www.stardustskateshop.com
Tactics | https://www.tactics.com
Holistic | https://holisticskateshop.com
IQ | https://www.iqskateshop.com
Lapstone and Hammer | https://www.lapstoneandhammer.com
One Up | https://oneupskateshop.com
Union | https://www.unionskates.com
Dogwood | https://dogwoodskateshop.com
Radio | https://www.radioskateshop.com
Civil | https://wearecivil.com
Cassette | https://www.cassetteskateshop.com
No Comply | https://nocomplyatx.com
Deli | https://deliskatesupply.com
Geometric | https://www.geometricskateshop.com
Select | https://slcth.shop
Rhythm | https://www.rhythmskateshop.com
Time Machine | https://timemachineskateshop.com
Directive | https://www.directiveboardshop.com
Skate Supply VA | https://skatesupplyva.com
Venue | https://venueskateboards.com
Somewhere | https://somewhereofficial.com
35th North | https://35thnorth.com
August | https://august-shop.com
Skatepark of Tampa | https://skateparkoftampa.com
Faces | https://www.facesskateshop.com
Rukus | https://www.rukus103.com
808 Skate | https://www.808skate.com
Silo | https://shop.silostore.com
Tenant | https://www.tenantny.com
"""

UA = "Mozilla/5.0 (compatible; personal-tee-swipe/1.0; one run per day)"
DELAY = 1.0        # seconds between requests to the same store
MAX_PAGES = 40     # 40 x 250 = 10,000 products per store, maximum

TEE = re.compile(r"\b(t-?shirts?|tees?)\b", re.I)
NOT_TEE = re.compile(
    r"\b(long ?sleeves?|l/s|hood(ie|ed|y)?|youth|kids?|toddler|infant|baby|golf tees?|tank)\b",
    re.I,
)
SIZE_OPTION = re.compile(r"size", re.I)
MEDIUM = re.compile(r"^(m|md|med|medium)\b", re.I)


def get_json(url, tries=3):
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                ctype = r.headers.get("Content-Type", "")
                body = r.read()
            if "json" not in ctype:
                raise ValueError(f"not a JSON feed ({ctype or 'no content type'})")
            return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < tries - 1:
                time.sleep(15 * (attempt + 1))
                continue
            raise
    raise RuntimeError("too many retries")


def store_products(base):
    for page in range(1, MAX_PAGES + 1):
        data = get_json(f"{base}/products.json?limit=250&page={page}")
        products = data.get("products") or []
        if not products:
            return
        yield from products
        time.sleep(DELAY)


def to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def tags_text(tags):
    if isinstance(tags, list):
        return " ".join(tags)
    return str(tags or "")


def is_tee(p):
    name = f"{p.get('title', '')} {p.get('product_type', '')}"
    if NOT_TEE.search(name):
        return False
    return bool(TEE.search(f"{name} {tags_text(p.get('tags'))}"))


def medium_sale_variant(p):
    """Return (variant, price, was) for the cheapest in-stock, on-sale size M variant."""
    opts = p.get("options") or []
    idx = next((i for i, o in enumerate(opts)
                if isinstance(o, dict) and SIZE_OPTION.search(o.get("name", ""))), None)
    best = None
    for v in p.get("variants") or []:
        if not v.get("available", True):
            continue
        if idx is not None and idx < 3:
            values = [v.get(f"option{idx + 1}")]
        else:
            values = [v.get("option1"), v.get("option2"), v.get("option3")]
        if not any(MEDIUM.match((x or "").strip()) for x in values):
            continue
        price, was = to_float(v.get("price")), to_float(v.get("compare_at_price"))
        if price and was and was > price and (best is None or price < best[1]):
            best = (v, price, was)
    return best


def image_for(p, v):
    fi = v.get("featured_image")
    if isinstance(fi, dict) and fi.get("src"):
        return fi["src"]
    imgs = p.get("images") or []
    return imgs[0].get("src") if imgs else None


def collect_store(name, base):
    host = urlparse(base).netloc
    found = []
    for p in store_products(base):
        if not is_tee(p):
            continue
        hit = medium_sale_variant(p)
        if not hit:
            continue
        v, price, was = hit
        found.append({
            "id": f"{host}:{p.get('id')}",
            "store": name,
            "title": p.get("title", "").strip(),
            "vendor": (p.get("vendor") or "").strip(),
            "price": price,
            "was": was,
            "off": round(100 * (1 - price / was)),
            "image": image_for(p, v),
            "url": f"{base}/products/{p.get('handle')}?variant={v.get('id')}",
        })
    return found


def dedupe(shirts):
    """The same shirt can be at many stores. Keep the cheapest copy."""
    best = {}
    for s in shirts:
        key = re.sub(r"\W+", " ", f"{s['vendor']} {s['title']}".lower()).strip()
        cur = best.get(key)
        if cur is None:
            best[key] = dict(s, also_at=[])
        elif s["price"] < cur["price"]:
            best[key] = dict(s, also_at=cur["also_at"] + [cur["store"]])
        else:
            cur["also_at"].append(s["store"])
    return list(best.values())


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "shirts.json"
    stores = [tuple(x.strip() for x in line.split("|", 1))
              for line in STORES.strip().splitlines() if "|" in line]
    all_shirts, ok, failed = [], [], {}
    for name, base in stores:
        base = base.rstrip("/")
        try:
            found = collect_store(name, base)
            ok.append(name)
            all_shirts.extend(found)
            print(f"OK    {name}: {len(found)} shirts", flush=True)
        except Exception as e:  # one bad store must not stop the run
            failed[name] = str(e)[:200]
            print(f"FAIL  {name}: {e}", flush=True)

    if not ok:
        print("All stores failed. shirts.json is not changed.")
        sys.exit(1)

    shirts = sorted(dedupe(all_shirts), key=lambda s: -s["off"])
    out = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(shirts),
        "stores_ok": ok,
        "stores_failed": failed,
        "shirts": shirts,
    }
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\n{len(shirts)} shirts from {len(ok)} stores. {len(failed)} stores failed.")


if __name__ == "__main__":
    main()
