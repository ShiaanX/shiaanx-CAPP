# Stock lists used by the quote

The quote's material section reads two spreadsheets that live in git, in this folder. Edit them in Excel,
commit, push, and redeploy. There is no conversion step: the backend reads the `.xlsx` files directly.

| File | What it is | How the quote uses it |
|---|---|---|
| `inhouse_inventory.xlsx` | Stock on hand: SKU, material, grade, shape, size, qty (pieces), condition, rack | Checked first. Match on Material + Grade + Shape + Size; the billet must be cuttable from the item and enough pieces must be on hand. In stock -> 0 days material lead time. |
| `supplier_directory.xlsx` | 32 suppliers + `Supplier_Grade_Map` (who sells which grade and shape) | Used when in-house has no match: filter the map by Grade + Shape, sort by Confidence (High, Medium, Low) then lead time, show the supplier from `Suppliers` by ID. |
| `material_prices.json` | Placeholder INR/kg per grade (neither spreadsheet has prices) | Material cost = billet weight x price. Replace with the real price list. |

## Rules worth knowing
- **Dummy data:** while the inventory `Notes` sheet says "dummy" or "demo data", every in-house item is flagged **sample** (the quote shows a sample-data badge). Replace the quantities with real stock and edit that note line, and the flag clears by itself.
- **Supplier lead times are planning estimates** (the file says so). Once you fill **Actual Lead Time (days)** for a supplier, the quote uses it instead of the estimate. Otherwise it uses the upper end of the range (conservative). `ShiaanX Verified` marks suppliers you have contacted.
- **Grade and shape names must match exactly between the two files** (for example `6061-T6`, `Plate`, `Round Bar`).
- **Quote grades supported:** 6061-T6, 6082-T6, 7075-T651 (the quote's material list). Add more in `demo_modules/stock_lists.py` (`GRADES`).
- **Shapes that can yield a block:** Plate, Flat Bar, Square Bar, Block, Round Bar. Tubes, angle and hex bar are ignored.
- Keep the sheet names and header row as they are (`Inventory`, `Notes`; `Suppliers`, `Supplier_Grade_Map`).
- Prices were deliberately left out of the supplier file (listing prices go stale): get real quotes.

Tests: `python -m unittest demo_modules.test_stock_lists` from `capp_service/`.
