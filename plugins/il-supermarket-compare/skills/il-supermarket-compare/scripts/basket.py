"""Total a shopping basket across stores from the prices you picked.

usage: python basket.py picks.json
picks.json:
{
  "stores": ["רמי לוי מבצע קדש 68 (3.2 km)", "אושר עד הקישון 11 (2.9 km)"],
  "items": [
    {"item": "חזה עוף 1.5 ק\"ג", "prices": [52.35, 58.35]},   # line total for the quantity, null = not found
    ...
  ]
}
Prints per-store totals, missing items, a like-for-like comparison over items every store has,
and the cherry-pick total (cheapest store per item).
"""
import json, sys

data = json.loads(open(sys.argv[1], encoding="utf-8").read())
stores, items = data["stores"], data["items"]
common = [it for it in items if all(p is not None for p in it["prices"])]

print(f'{"פריט":32}' + "".join(f"{s[:18]:>20}" for s in stores))
for it in items:
    row = it["prices"]
    best = min(p for p in row if p is not None) if any(p is not None for p in row) else None
    cells = "".join(f'{("—" if p is None else f"{p:.2f}" + ("*" if p == best else "")):>20}' for p in row)
    print(f'{it["item"][:32]:32}{cells}')

print("\nסה\"כ (פריטים שנמצאו):")
for i, s in enumerate(stores):
    total = sum(it["prices"][i] or 0 for it in items)
    missing = [it["item"] for it in items if it["prices"][i] is None]
    print(f"  {s}: {total:.2f} ₪" + (f"  | חסר: {', '.join(missing)}" if missing else ""))

if common:
    totals = [sum(it["prices"][i] for it in common) for i in range(len(stores))]
    low = min(totals)
    print(f"\nהשוואה הוגנת ({len(common)} פריטים שיש בכל החנויות):")
    for s, t in sorted(zip(stores, totals), key=lambda x: x[1]):
        print(f"  {s}: {t:.2f} ₪" + ("  <- הכי זול" if t == low else f"  (+{(t / low - 1) * 100:.1f}%)"))

pick = sum(min(p for p in it["prices"] if p is not None) for it in items if any(p is not None for p in it["prices"]))
print(f"\nקנייה מפוצלת (הכי זול לכל פריט): {pick:.2f} ₪")
