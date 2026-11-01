---
name: il-supermarket-compare
description: Compare today's supermarket prices in Israel for a shopping list near an address. Takes a location (address in Israel) and a shopping list (Hebrew or English), finds supermarket branches within a radius (default 4 km), downloads each chain's official price-transparency files for today, matches the items, and reports which store is cheapest for the whole basket. Use when the user asks where it's cheapest to buy their groceries / shopping list, "איפה הכי זול", השוואת מחירים לסל קניות, or gives a רשימת קניות with an address.
---

# Israeli supermarket basket comparison

Israeli chains must publish full XML price files per branch, updated daily (חוק קידום התחרות בענף המזון).
This skill uses those official files. It does **not** scrape comparison sites.

## Inputs
- **Location**: an address in Israel ("הרצל 50, רמת גן"). If the user gave only a city, use it, but warn that distances are measured from the city centre.
- **Shopping list**: items, with quantities if given.
- **Radius** (optional): default **4 km** straight line. 4 km from Ramat Gan reaches the cheap Bnei Brak branches (Rami Levy on Mivtza Kadesh at 3.2 km, Osher Ad on HaKishon at 2.9 km). Use a smaller radius if the user says they're walking, larger if they say they drive far.

Don't ask about brands or quantities up front. Choose sensible defaults (see Matching) and state them in the answer.

## If the price sites can't be reached, stop
This skill needs open internet access to the chains' price sites and to nominatim.openstreetmap.org.
Sandboxed environments block those: the regular Claude chat (claude.ai / the desktop app's Chat tab) and other cloud containers with a network allowlist.
If `find_stores.py` or `prices.py` fails for every chain with connection, proxy or 403 errors:
- **Don't** substitute web searches, news articles or price surveys for the comparison. A general "Rami Levy is usually cheapest" answer is not what the user asked for.
- Tell the user plainly, in their language and without technical jargon, that this tool only works in **Claude Code** on their computer (the **Code** tab in the Claude desktop app), not in the regular chat. Suggest they open the Code tab and send the same message there.
- If only some chains fail, continue with the rest and name the ones that were skipped.

## Workflow

Scripts are in `scripts/` next to this file. Run them with `python` from that folder, with `PYTHONIOENCODING=utf-8`. Do not use `python -I`, because `requests` is installed in user site-packages.
Cache: `~/.cache/il-supermarkets` (override with `IL_SUPERMARKETS_CACHE`). It is short on purpose, because Windows breaks on paths over 260 chars. Store lists and price files are cached per day; geocodes are cached permanently.

1. **Find stores**
   `python find_stores.py "<address>" --radius 4`
   - Geocodes with OpenStreetMap Nominatim (1 request/second). The first run in a new area takes a few minutes; run it in the background.
   - Prints `km | chain:store_id | name | address` and writes `stores_nearby.json`.
   - Rows marked "מיקום משוער" are city-centre fallbacks. Mention that if one of them ends up as a winner.
2. **Download prices** for the candidates
   `python prices.py --nearby` downloads **every** branch in range of the discount banners (Rami Levy, Osher Ad, Yochananof, Keshet, Yesh Hesed, Universe, Deal), plus the nearest branch of each other banner (Shufersal Sheli/Express, Carrefour City/Market, Tiv Taam, am:pm...). That's typically 20-30 stores and takes a few minutes, so run it in the background.
   Discount chains price branch by branch. Rami Levy Bnei Brak was ~18% cheaper than Rami Levy Givatayim 3 km away, so far big branches matter.
   You can also pick explicitly: `python prices.py shufersal:70 RamiLevi:16 osherad:11`.
   "no PriceFull file published" means the branch is closed or didn't publish today (common on Shabbat). Skip it.
   For the totals, compare the 3-6 most promising stores: the cheapest-looking branch of each discount banner, plus the nearest regular store.
3. **Search** for candidates. Write a `queries.json` with one entry per list item: `{"item": ["include regex", "exclude regex"]}`. Then run
   `python search.py queries.json --top 5`.
   Names in the files are short and abbreviated (תפו"א, ג.צהובה, דנונ.פרו), so keep the regexes loose and exclude the obvious noise (snacks, sauces, pet food, pickles).
   Do a second pass with refined regexes for items that came back empty or noisy.
4. **Pick one comparable product per store**, then write `picks.json` with line totals for the requested quantity (null = not found) and run `python basket.py picks.json`.
5. **Answer** in the user's language with:
   - The winner: store, address and distance.
   - A table of totals per store.
   - The like-for-like comparison, over the items every store has, in ₪ and %.
   - Notable item differences.
   - Items missing per store.
   - The assumptions you made.

## Matching rules (important for honest totals)
- `is_weighted=1` → the price is **per kg**. Multiply by the quantity. Default quantities when not given: 1 kg per vegetable or fruit, ½ kg lemons, 2 kg potatoes, ½ kg per fish. For packaged items, one pack.
- Compare the **same kind of product**:
  - Fresh vs frozen (e.g. Shufersal's cheap שייטל was frozen).
  - Boneless vs bone-in ("חזה עוף שלם" / "חצוי" is bone-in and roughly half the price of פילה).
  - Pack size (normalize or use the same size).
  - Organic vs regular.
- Store-brand items are legitimately cheaper (e.g. רמי לוי 28% cheese 400 g at 14 ₪). Use the comparable item in the totals and mention the cheaper alternative separately.
- If an item isn't found in a store, leave it null. Don't guess. `basket.py` keeps those items out of the like-for-like comparison.
- Osher Ad's files label weighted items with unit "יחידה" while `bisweighted=1`. Treat those as per kg. Quantity `0.00` in some chains just means the field wasn't filled.

## Caveats to state
- These are regular shelf prices from today's files. Promotions and club prices are **not** included (they live in Promo files, which this skill doesn't parse yet).
- Distances are straight-line, not driving distances.
- Portals covered:
  - Shufersal, including Yesh Hesed, Universe, Deal and Express.
  - Carrefour.
  - publishedprices.co.il: Rami Levi, Osher Ad, Yochananof, Tiv Taam, Keshet Teamim, Dor Alon / am:pm, Freshmarket, Salach Dabach, Stop Market and Politzer.
  - **Not** covered: Victory, Hazi Hinam, Mahsanei HaShuk, Yayno Bitan. Say so if those are likely nearby.
- A portal that is down just gets skipped with a warning. Report which chains were skipped.

## Don'ts
- Don't scrape chp.co.il or similar sites. CHP obfuscates its results with hidden decoy characters as anti-bot protection; respect that.
- Don't disable TLS verification. The portals work with normal certificate checks.
