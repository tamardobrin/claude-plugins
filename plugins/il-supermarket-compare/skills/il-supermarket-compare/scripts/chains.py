"""Fetch store lists and full price files from Israeli chains' price-transparency sites.

Every chain must publish XML price files by law (חוק קידום התחרות בענף המזון).
Covered portals:
  - Shufersal (incl. Yesh Hesed, Universe, Deal, Express, Sheli, BE)
  - url.publishedprices.co.il (public per-chain usernames, empty password)
  - Carrefour (incl. Carrefour City / Market)
"""
import datetime, gzip, json, os, re
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

CACHE = Path(os.environ.get("IL_SUPERMARKETS_CACHE", Path.home() / ".cache" / "il-supermarkets"))
CACHE.mkdir(parents=True, exist_ok=True)
TODAY = datetime.date.today().strftime("%Y%m%d")
UA = {"User-Agent": "il-supermarket-compare/1.0 (personal price comparison)"}

PUBLISHEDPRICES_USERS = {
    "RamiLevi": "רמי לוי",
    "osherad": "אושר עד",
    "yohananof": "יוחננוף",
    "TivTaam": "טיב טעם",
    "Keshet": "קשת טעמים",
    "doralon": "דור אלון (am:pm)",
    "freshmarket": "פרשמרקט",
    "SalachD": "סאלח דבאח",
    "Stop_Market": "סטופ מרקט",
    "politzer": "פוליצר",
}


def parse_xml(content):
    try:
        content = gzip.decompress(content)
    except OSError:
        pass
    return ET.fromstring(content)


def records(root, tag):
    """Yield dicts (lower-cased keys) for every element named `tag` that has children."""
    for el in root.iter():
        if el.tag.lower() == tag and len(el):
            yield {c.tag.lower(): (c.text or "").strip() for c in el}


def store_rows(root, chain_key, chain_name):
    out = []
    for d in records(root, "store"):
        out.append({"chain": chain_key, "chain_name": chain_name, "store_id": d.get("storeid", "").lstrip("0") or "0",
                    "name": d.get("storename", ""), "address": d.get("address", ""), "city": d.get("city", ""),
                    "subchain": d.get("subchainname", "")})
    return out


def _latest(files, store_id):
    if not files:
        raise RuntimeError(f"no PriceFull file published for store {store_id} (closed today / Shabbat?)")
    return files[-1]


# ---------------- Shufersal ----------------
SHUF = "https://prices.shufersal.co.il/FileObject/UpdateCategory"

def _shuf_links(cat, store=0):
    h = requests.get(SHUF, params={"catID": cat, "storeId": store}, headers=UA, timeout=60).text
    return re.findall(r'href="(https://[^"]+)"', h.replace("&amp;", "&"))

def shufersal_stores():
    root = parse_xml(requests.get(_shuf_links(5)[0], headers=UA, timeout=120).content)
    return store_rows(root, "shufersal", "שופרסל")

def shufersal_pricefull(store_id):
    url = _latest([u for u in _shuf_links(2, store_id) if "PriceFull" in u], store_id)
    return parse_xml(requests.get(url, headers=UA, timeout=300).content)


# ---------------- publishedprices.co.il ----------------
PP = "https://url.publishedprices.co.il"

def _pp_session(user):
    s = requests.Session()
    s.headers.update(UA)
    tok = re.search(r'name="csrftoken" content="([^"]+)"', s.get(PP + "/login", timeout=60).text).group(1)
    s.post(PP + "/login/user", data={"username": user, "password": "", "csrftoken": tok}, timeout=60)
    m = re.search(r'name="csrftoken" content="([^"]+)"', s.get(PP + "/file", timeout=60).text)
    if not m:
        raise RuntimeError(f"publishedprices login failed for {user}")
    s.tok = m.group(1)
    return s

def _pp_ls(s, search):
    r = s.post(PP + "/file/json/dir", data={"sEcho": 1, "iDisplayStart": 0, "iDisplayLength": 100000,
               "sSearch": search, "cd": "/", "csrftoken": s.tok}, timeout=60).json()
    return sorted((f["fname"] for f in r["aaData"]), key=lambda n: n.split("-")[-1])

def pp_stores(user):
    s = _pp_session(user)
    root = parse_xml(s.get(PP + "/file/d/" + _pp_ls(s, "Stores")[-1], timeout=120).content)
    return store_rows(root, user, PUBLISHEDPRICES_USERS[user])

def pp_pricefull(user, store_id):
    s = _pp_session(user)
    f = _latest([n for n in _pp_ls(s, "PriceFull") if f"-{int(store_id):03d}-" in n], store_id)
    return parse_xml(s.get(PP + "/file/d/" + f, timeout=300).content)


# ---------------- Carrefour ----------------
CAR = "https://prices.carrefour.co.il"

def _car_index():
    h = requests.get(CAR + "/", headers=UA, timeout=60).text
    path = re.search(r"const path = '(\d+)'", h).group(1)
    names = sorted(set(re.findall(r'"name":"([^"]+)"', h)), key=lambda n: n.split("-")[-1])
    return path, names

def carrefour_stores():
    path, names = _car_index()
    f = [n for n in names if n.startswith("Stores")][-1]
    return store_rows(parse_xml(requests.get(f"{CAR}/{path}/{f}", headers=UA, timeout=120).content), "carrefour", "קרפור")

def carrefour_pricefull(store_id):
    path, names = _car_index()
    f = _latest([n for n in names if n.startswith("PriceFull") and f"-{int(store_id):03d}-" in n], store_id)
    return parse_xml(requests.get(f"{CAR}/{path}/{f}", headers=UA, timeout=300).content)


# ---------------- dispatch ----------------
def all_chain_keys():
    return ["shufersal", "carrefour", *PUBLISHEDPRICES_USERS]

def stores_for(chain):
    if chain == "shufersal":
        return shufersal_stores()
    if chain == "carrefour":
        return carrefour_stores()
    return pp_stores(chain)

def pricefull_for(chain, store_id):
    if chain == "shufersal":
        return shufersal_pricefull(store_id)
    if chain == "carrefour":
        return carrefour_pricefull(store_id)
    return pp_pricefull(chain, store_id)


def cached_json(name, fn):
    """Day-scoped JSON cache."""
    p = CACHE / f"{name}-{TODAY}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    data = fn()
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data
