# Motor Mount — Two-Shop Process Comparison

**TS (Sinumerik 828D):** 4 setups, 19 operation blocks
**Krishna Engg (PowerMILL/Fanuc):** 3 settings, 20 TAP files

## 1. Setup / Setting Count

| Aspect | TS | Krishna |
|--------|-----|---------|
| Setup count | 4 | 3 |
| Has dedicated finish re-setup | YES (setup 3 re-does setup 1 floors) | NO |
| Bore operation separate setup | YES (setup 4) | YES (3rd setting) |
| 2nd face in own setup | YES (setup 2 = flip) | YES (2nd setting = flip) |

**Why TS uses 4:** Setup 3 is a *finish-only* re-run of setup 1 floors after flipping and doing setup 2. This gives better dimensional accuracy on the base face by revisiting with the part more stable. Krishna skips this — they achieve adequate accuracy in fewer setups.

## 2. Tool Choices by Operation

| Logical Operation | TS Tool | Krishna Tool | Match? |
|-------------------|---------|--------------|--------|
| Main roughing (bulk material removal) | 10mm EM, Dynamic (HSM) | 12mm EM, conventional | VARIABLE — dia & strategy differ |
| Outer profile finish | 10mm EM (S=2200, F=500) | 12mm EM (S=4500, F=1000) | VARIABLE — both use largest EM |
| Medium pocket / step | 8mm EM | 8mm EM | CONSISTENT ✓ |
| Small pocket / cavity | 3–4mm EM | 2–4mm EM | CONSISTENT (range) |
| Corner cleanup | 4mm EM | 2mm EM | VARIABLE — Krishna goes smaller |
| Fillet / radius finish | 8mm Bull Nose R1 + 5mm BN | 4mm Ball Nose | VARIABLE — both use BN/ball nose |
| Small recess / slot | 3mm EM | 2mm EM | VARIABLE |
| Bore ⌀16.1 | 10mm EM circular interp | 10mm EM | CONSISTENT ✓ — both use 10mm EM |
| Center drill | 2mm center drill | NOT FOUND in TAP files | VARIABLE — Krishna may drill on separate machine |
| Twist drill ⌀2.5 | 2.5mm drill | NOT FOUND in TAP files | VARIABLE |
| Twist drill ⌀3.2 | 3.2mm drill | NOT FOUND in TAP files | VARIABLE |
| Chamfer | 10mm chamfer mill | NOT FOUND in TAP files | VARIABLE — Krishna may use EM edge |
| Ball nose fillet | 3–5mm ball nose | 3–4mm ball nose | CONSISTENT (type) ✓ |

## 3. Feeds & Speeds by Operation

| Operation | TS S (rpm) | TS F (mm/min) | Krishna S (rpm) | Krishna F (mm/min) | Within ±20%? |
|-----------|------------|---------------|-----------------|-------------------|--------------|
| Bulk roughing (10mm EM) | 4461–4557 | 10000 (Dynamic) | 3000 | 1000 | NO — TS 3× faster F, HSM strategy |
| Main profile finish (10mm EM) | 2200 | 500 | 3000 | 1000 | S: within 36%, F: within 100% — borderline |
| Step / flat finish (8–10mm EM) | 2200–2800 | 300–500 | 3000 | 500–1000 | S: within 36% — CONSISTENT |
| Small EM (2–4mm) | 2200–3000 | 500–800 | 3000–7500 | 500–1000 | S: VARIABLE (Krishna higher) |
| Center drill | 1000 | 80 | N/A | N/A | — |
| Twist drill ⌀2.5–3.2 | 1200–1500 | 70–80 | N/A | N/A | — |
| Ball nose radius finish | 2500–4500 | 500–1000 | 3000–7500 | 500–1000 | VARIABLE |
| Bore ⌀16.1 circular interp | 2500 | 800 | 3000 | 1000 | S: within 20% ✓, F: within 25% — CONSISTENT |
| Chamfer mill | 900 / 4500 | 80 / 1000 | N/A | N/A | — |

## 4. Operations One Shop Did That the Other Skipped

| Operation | TS | Krishna | Notes |
|-----------|-----|---------|-------|
| HSM/Dynamic roughing toolpath | YES (CAM strategy) | NO — conventional passes | TS machine + CAM supports trochoidal |
| Dedicated finish re-setup (setup 3) | YES | NO | TS corrects floor flatness after flip |
| Center drilling before holes | YES | NOT in TAP files | Krishna may drill on VMC manually or separate cycle |
| Dedicated chamfer mill | YES | NOT in TAP files | Krishna possibly uses EM chamfer or visual deburr |
| Bull nose (flat-bottom radius tool) | YES (8mm BNR1) | NO — uses ball nose only | TS distinguishes BN from ball nose |
| 3mm ball nose for fillet detail | YES (setup 2) | NO 3mm ball nose in 1st setting | 2nd setting has 3mm BN |

## 5. Classification: CONSISTENT vs VARIABLE

| Finding | Classification | Confidence |
|---------|---------------|------------|
| 10mm EM used for ⌀16.1 bore via circular interpolation | CONSISTENT | HIGH |
| 8mm EM used for medium pockets | CONSISTENT | HIGH |
| Ball nose / bull nose used for fillet radius finishing | CONSISTENT | HIGH |
| Separate setup for flip (2nd face) | CONSISTENT | HIGH |
| Bore and long pocket done in last setup | CONSISTENT | HIGH |
| Drilling (spot → twist) before tapped holes | CONSISTENT in intent; TS explicit, Krishna implicit | MEDIUM |
| Roughing tool = largest affordable EM (10–12mm) | CONSISTENT | HIGH |
| Step bottom and wall finish uses lower S than rough | CONSISTENT | HIGH |
| Step finish F = 300–500 mm/min | CONSISTENT | MEDIUM |
| Dynamic/HSM roughing strategy | VARIABLE — TS yes, Krishna no | SHOP PREF |
| Extra finish re-setup (setup 3) | VARIABLE — TS yes, Krishna no | SHOP PREF |
| Chamfer via dedicated chamfer mill | VARIABLE | SHOP PREF |
| Small-feature EM diameter (2mm vs 3mm vs 4mm) | VARIABLE | SHOP PREF |
| Absolute spindle speed values | VARIABLE (±40%) | SHOP PREF |
| Roughing feed rate | VARIABLE (1000 vs 10000) | STRATEGY DIFF |
