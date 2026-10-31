"""Download today's full price file for stores and save a compact TSV per store.

usage: python prices.py shufersal:70 RamiLevi:16 carrefour:469 ...
       python prices.py --nearby [K]   # every discount-chain branch in range + the K nearest of each other banner (default 1)
TSV columns: code, name, price, quantity, unit, is_weighted(1 = price per kg), unit_price, manufacturer
"""
import json, sys

from chains import CACHE, TODAY, pricefull_for, records

COLS = ["itemcode", "itemname", "itemprice", "quantity", "unitofmeasure", "bisweighted", "unitofmeasureprice", "manufacturername"]


def tsv_path(chain, store_id):
    return CACHE / f"{chain}-{store_id}-{TODAY}.tsv"


def banner(s):
    """Shufersal and Carrefour run several formats (יש חסד, יוניברס, אקספרס / סיטי, מרקט) with very different prices."""
    words = s["name"].replace("שופרסל", "").replace("קרפור", "").split()
    if s["chain"] in ("shufersal", "carrefour") and words:
        return f'{s["chain"]}:{words[0]}'
    return s["chain"]


# Discount banners price branch by branch (Rami Levy Bnei Brak was ~18% below Rami Levy Givatayim),
# so every branch in range is worth checking, not just the nearest.
DISCOUNT = {"RamiLevi", "osherad", "yohananof", "Keshet", "shufersal:יש", "shufersal:יוניברס", "shufersal:דיל"}


def nearby_targets(per_banner):
    near = json.loads((CACHE / "stores_nearby.json").read_text(encoding="utf-8"))
    seen, out = {}, []
    for s in near:  # already sorted by distance
        b = banner(s)
        if b in DISCOUNT or seen.get(b, 0) < per_banner:
            seen[b] = seen.get(b, 0) + 1
            out.append((s["chain"], s["store_id"]))
    return out


def download(chain, store_id):
    p = tsv_path(chain, store_id)
    if p.exists():
        return p, "cached"
    rows = ["\t".join(d.get(k, "").replace("\t", " ") for k in COLS) for d in records(pricefull_for(chain, store_id), "item")]
    p.write_text("\n".join(rows), encoding="utf-8")
    return p, f"{len(rows)} items"


def main():
    args = sys.argv[1:]
    if args and args[0] == "--nearby":
        targets = nearby_targets(int(args[1]) if len(args) > 1 else 1)
    else:
        targets = [a.split(":", 1) for a in args]
    for chain, sid in targets:
        try:
            p, info = download(chain, sid)
            print(f"ok   {chain}:{sid}  {info}  {p.name}")
        except Exception as e:  # noqa: BLE001 - report and continue with other stores
            print(f"FAIL {chain}:{sid}  {e}")


if __name__ == "__main__":
    main()
