"""Search downloaded price files for candidate products.

usage:
  python search.py queries.json [--top 5] [--stores shufersal:70,RamiLevi:16]
queries.json: {"מלפפון": ["^מלפפון", "במלח|בחומץ|בייבי"], "חזה עוף": ["חזה עוף|פילה עוף", "קפוא|טחון|שלם"]}
  value = [include regex, exclude regex ("" for none)], matched against the item name.
Without --stores, searches every store from stores_nearby.json that has a TSV for today.
Weighted items (is_weighted=1) are priced per kg; check the unit column, pack sizes differ.
"""
import argparse, json, re

from chains import CACHE, TODAY


def load(path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        p = line.split("\t")
        if len(p) < 8:
            continue
        try:
            p[2] = float(p[2])
        except ValueError:
            continue
        rows.append(p)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("queries")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--stores", default="")
    a = ap.parse_args()

    near = {f'{s["chain"]}:{s["store_id"]}': s for s in json.loads((CACHE / "stores_nearby.json").read_text(encoding="utf-8"))} \
        if (CACHE / "stores_nearby.json").exists() else {}
    keys = a.stores.split(",") if a.stores else list(near)
    stores = {}
    for k in keys:
        chain, sid = k.split(":", 1)
        p = CACHE / f"{chain}-{sid}-{TODAY}.tsv"
        if p.exists():
            s = near.get(k, {})
            label = f'{s.get("chain_name", chain)} {s.get("name", sid)} ({s.get("km", "?")} km) [{k}]'
            stores[label] = load(p)

    queries = json.loads(open(a.queries, encoding="utf-8").read())
    for item, (inc, exc) in queries.items():
        print(f"\n######## {item}")
        for label, rows in stores.items():
            hits = sorted((r for r in rows if re.search(inc, r[1]) and not (exc and re.search(exc, r[1]))), key=lambda r: r[2])
            print(f"  -- {label} ({len(hits)})")
            for r in hits[:a.top]:
                per = 'לק"ג' if r[5] == "1" else ""
                print(f"     {r[2]:7.2f} {per:5} | {r[1]} | {r[3]} {r[4]} | {r[7][:15]}")


if __name__ == "__main__":
    main()
