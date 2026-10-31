# il-supermarket-compare

Find the cheapest supermarket near you in Israel for a whole shopping list.

## Usage

Give Claude an address and a list:

> איפה הכי זול לקנות את זה? אני גר/ה ברחוב הרצל ברמת גן
> מלפפונים, חזה עוף 1.5 ק"ג, גבינה צהובה, ביצים...

Optionally name a radius ("ברדיוס של 2 ק"מ"). The default is 4 km, straight line.

## What it does

1. Finds supermarket branches within the radius. Addresses are geocoded with OpenStreetMap, and the results are cached.
2. Downloads today's full price file for each branch. Israeli chains must publish these by law (חוק קידום התחרות בענף המזון). It takes every branch of the discount chains in range, because they price branch by branch, plus the nearest branch of every other banner.
3. Matches each list item to comparable products: fresh vs frozen, boneless vs bone-in, same pack size.
4. Reports per-store basket totals, a like-for-like comparison over the items every store has, the items missing at each store, and the cherry-pick total.

**Chains covered:**
- Shufersal, including Yesh Hesed, Universe, Deal and Express
- Carrefour
- Rami Levy
- Osher Ad
- Yochananof
- Tiv Taam
- Keshet Teamim
- am:pm
- Freshmarket
- Salach Dabach
- Stop Market
- Politzer

**Not covered yet:** Victory, Hazi Hinam, Mahsanei HaShuk.

## Requirements

- Claude Code on your computer: the skill runs Python scripts and needs internet access.
- Python 3.9+ with `requests` (`pip install requests`).

## Limitations

- Regular shelf prices only. Promotions and club prices are not included yet.
- Distances are straight-line, not driving.
- Some branches don't publish on Shabbat. They are skipped with a note.
