"""Find supermarket branches within a radius of an address.

usage: python find_stores.py "הרצל 50, רמת גן" [--radius 4] [--chains shufersal,RamiLevi,...]
Writes stores_nearby.json to the cache dir and prints a table sorted by distance.
"""
import argparse, json, math, re, sys, time

import requests

from chains import CACHE, UA, all_chain_keys, cached_json, stores_for

GEO_CACHE = CACHE / "geocode.json"
_geo = json.loads(GEO_CACHE.read_text(encoding="utf-8")) if GEO_CACHE.exists() else {}
_last = [0.0]


def geocode(q):
    """Nominatim (OSM) lookup, permanently cached; respects the 1 request/second policy."""
    if q in _geo:
        return _geo[q]
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search", headers=UA, timeout=30,
                         params={"q": q, "format": "json", "limit": 1, "countrycodes": "il"}).json()
    except (requests.RequestException, ValueError):
        r = []
    _last[0] = time.time()
    _geo[q] = [float(r[0]["lat"]), float(r[0]["lon"])] if r else None
    GEO_CACHE.write_text(json.dumps(_geo, ensure_ascii=False), encoding="utf-8")
    return _geo[q]


def clean_address(addr, city):
    """Normalize the messy store-file addresses ("רח' הרוא\"ה 152", "ירושלים  70", "תרצה 19 ר\"ג")."""
    a = re.sub(r"\(.*?\)", " ", addr)
    a = re.sub(r"\b(רח(וב)?['.]?|שד(רות)?['.]?)\s*", "", a)
    a = re.sub(r'ר"ג|ת"א|ב"ב|פינת.*|מ\.מסחרי|מרכז מסחרי', " ", a)
    a = a.replace(city, " ").replace('"', "").replace("״", "")
    return re.sub(r"\s+", " ", a).strip(" ,-")


def locate_store(s):
    """Try progressively looser geocoding queries; None if the street can't be found."""
    if not s["address"] or s["address"].startswith("http"):
        return None
    a = clean_address(s["address"], s["city"])
    tries = [f'{s["address"]}, {s["city"]}', f"{a}, {s['city']}"]
    street = re.sub(r"\d+[-\d]*", "", a).strip()
    if street and street != a:
        tries.append(f"{street}, {s['city']}")
    for q in dict.fromkeys(tries):
        g = geocode(q)
        if g:
            return g
    return None


def is_supermarket(s):
    """Drop pharmacies (Shufersal BE) and online-only shops listed in the stores files."""
    n = f'{s["name"]} {s["address"]}'
    return not (re.search(r"\bBE\b|אונליין|online|@|https?://", n, re.I))


def km(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    return 2 * 6371 * math.asin(math.sqrt(math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))


def city_names():
    """CBS locality code -> Hebrew name (stores files often give the city as a code, e.g. 8600)."""
    def fetch():
        r = requests.get("https://data.gov.il/api/3/action/datastore_search", timeout=60,
                         params={"resource_id": "5c78e9fa-c2e2-4771-93ff-7f400a12f7ba", "limit": 5000}).json()
        return {str(int(x["סמל_ישוב"])): x["שם_ישוב"].strip() for x in r["result"]["records"]}
    try:
        return cached_json("cities", fetch)
    except Exception as e:  # noqa: BLE001 - optional enrichment
        print(f"warning: could not load city codes ({e})", file=sys.stderr)
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    ap.add_argument("--radius", type=float, default=4.0, help="km, straight line (default 4)")
    ap.add_argument("--chains", default=",".join(all_chain_keys()))
    a = ap.parse_args()

    home = geocode(a.address)
    if not home:
        sys.exit(f"could not geocode {a.address!r}; try 'street number, city'")
    codes = city_names()

    stores = []
    for chain in a.chains.split(","):
        try:
            rows = cached_json(f"stores-{chain}", lambda c=chain: stores_for(c))
        except Exception as e:  # noqa: BLE001 - one broken portal shouldn't stop the search
            print(f"warning: skipping {chain}: {e}", file=sys.stderr)
            continue
        for s in rows:
            c = s["city"].strip()
            s["city"] = codes.get(c.lstrip("0"), c) if c.isdigit() else c
        stores += rows

    # Pre-filter by city centroid so we only geocode street addresses near home.
    near_cities = set()
    for c in {s["city"] for s in stores if s["city"]}:
        g = geocode(f"{c}, ישראל")
        if g and km(home, g) <= a.radius + 8:
            near_cities.add(c)

    out = []
    for s in stores:
        if s["city"] not in near_cities or not is_supermarket(s):
            continue
        g = locate_store(s)
        approx = g is None
        d = km(home, g or geocode(f'{s["city"]}, ישראל'))
        # A city-centre fallback can be off by a few km, so only trust it when well inside the radius.
        if d <= (a.radius - 1.5 if approx else a.radius):
            out.append({**s, "km": round(d, 2), "approx_location": approx})
    out.sort(key=lambda s: s["km"])

    (CACHE / "stores_nearby.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in out:
        flag = " (מיקום משוער - מרכז העיר)" if s["approx_location"] else ""
        print(f'{s["km"]:5.2f} km | {s["chain"]}:{s["store_id"]} | {s["chain_name"]} {s["name"]} | {s["address"]}, {s["city"]}{flag}')
    print(f"\n{len(out)} stores within {a.radius} km -> {CACHE / 'stores_nearby.json'}")


if __name__ == "__main__":
    main()
