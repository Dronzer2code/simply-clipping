# SC_RESULTS.md — Simply Clipping test bench results

Overnight batch: 10 seeds x 6 scenarios (full Suzuka races, 2026 post-Miami rules), seeds 1-5 = tune set, 6-10 = test set. Mean ± spread over seeds. Columns: the sim's **built-in** Radar + built-in alerts, the **dumb rule** ("car ahead slower on this straight -> ATTACK"), and **Simply Clipping** v1 (the owner's estimator, `simply_clipping/`, tag `sc-v1`): tuned on seeds 1-5 only (`docs/results/SC_TUNING.md`), the test set run once with the final config.

Simply Clipping v1 against the targets (test set, `docs/spec/SIMPLY_CLIPPING_SPEC.md` TARGETS): energy MAE 0.36-0.88 MJ vs built-in 0.84-1.28 (lower in every scenario); confidence honest (ECE 4-10 % per scenario, 0.9 % pooled: stated 0.84 -> right 84 %; built-in 18-34 %); CLIP precision 53-66 % vs 4-6 % (CLIP recall lower, 19-27 % vs 35-41 %); repass incident 67 % vs 33 %; closing-speed incident 0 % vs 0 % (spec O-3); normal-race ATTACK precision 0 % vs 8 % (ATTACK rarely fires there with the 1.2 MJ margin; right per truth higher than the built-in in every scenario); alerts per race 30-77.

Rows: "within 0.5 MJ" = share of estimates within 0.5 MJ of the true battery (spec O-1); "confidence ECE" = mean gap between stated confidence and that hit rate (0 = honest); lead times are the median seconds from the first matching alert to the event. Rebuild: `python -m pitwall_sim.evaluate.batch --batch data/exports/batch --write docs/results/SC_RESULTS.md`; Simply Clipping: `python -m pitwall_sim.bench --sc-module simply_clipping --scenario all --seeds 6-10` (docs/spec/SIMPLY_CLIPPING_BRIDGE.md).

## TEST SET (seeds 6-10)

### battles (seeds 6, 7, 8, 9, 10; target produced in 5/5)

| metric | built-in | dumb rule | Simply Clipping |
| --- | --- | --- | --- |
| energy MAE MJ | 0.84 ± 0.04 | - | 0.52 ± 0.03 |
| energy p90 MJ | 1.75 ± 0.05 | - | 1.32 ± 0.05 |
| MAE conf>=0.5 | 0.94 ± 0.11 | - | 0.50 ± 0.04 |
| within 0.5 MJ | 37% ± 3% | - | 60% ± 2% |
| confidence ECE | 30% ± 1% | - | 8% ± 2% |
| CLIP precision | 6% ± 0% | - | 66% ± 4% |
| CLIP recall | 41% ± 1% | - | 27% ± 1% |
| false CLIP in taper | 1% ± 0% | - | 1% ± 0% |
| CdA abs err straight % | - | - | 4.19 ± 0.56 |
| CdA abs err corner % | - | - | 6.76 ± 0.54 |
| CdA trap err straight % | - | - | - |
| ATTACK recall | 70% ± 10% | 80% ± 3% | 3% ± 4% |
| ATTACK precision | 36% ± 6% | 32% ± 9% | 14% ± 20% |
| ATTACK right | 46% ± 9% | 38% ± 9% | 64% ± 12% |
| ATTACK lead s (median) | 46.50 ± 32.47 | 88.25 ± 26.53 | 120.06 ± 70.81 |
| DEFEND recall | 37% ± 16% | 0% ± 0% | 49% ± 20% |
| DEFEND precision | 23% ± 11% | - | 17% ± 11% |
| DEFEND right | 43% ± 9% | - | 68% ± 9% |
| DEFEND lead s (median) | 48.30 ± 35.61 | - | 134.20 ± 37.56 |
| REPASS recall | 25% ± 43% | 0% ± 0% | 8% ± 14% |
| REPASS precision | 2% ± 4% | - | 1% ± 3% |
| CLOSING recall | 0% ± 0% | 0% ± 0% | 6% ± 2% |
| CLOSING precision | 7% ± 7% | - | 16% ± 2% |
| alerts per race | 64.40 ± 12.85 | 53.40 ± 10.58 | 76.80 ± 22.94 |
| incident pass | - | - | - |

### cda_trap (seeds 6, 7, 8, 9, 10; target produced in 5/5)

| metric | built-in | dumb rule | Simply Clipping |
| --- | --- | --- | --- |
| energy MAE MJ | 0.85 ± 0.05 | - | 0.60 ± 0.02 |
| energy p90 MJ | 1.90 ± 0.09 | - | 1.65 ± 0.12 |
| MAE conf>=0.5 | 0.80 ± 0.08 | - | 0.39 ± 0.03 |
| within 0.5 MJ | 41% ± 1% | - | 61% ± 1% |
| confidence ECE | 34% ± 1% | - | 4% ± 1% |
| CLIP precision | 4% ± 0% | - | 53% ± 5% |
| CLIP recall | 36% ± 1% | - | 21% ± 1% |
| false CLIP in taper | 1% ± 0% | - | 2% ± 0% |
| CdA abs err straight % | - | - | 3.56 ± 0.68 |
| CdA abs err corner % | - | - | 4.04 ± 0.43 |
| CdA trap err straight % | - | - | 4.63 ± 0.58 |
| ATTACK recall | 47% ± 40% | 90% ± 20% | 30% ± 27% |
| ATTACK precision | 11% ± 9% | 7% ± 4% | 6% ± 7% |
| ATTACK right | 71% ± 23% | 58% ± 13% | 98% ± 3% |
| ATTACK lead s (median) | 162.75 ± 47.01 | 106.83 ± 30.51 | 171.54 ± 51.30 |
| DEFEND recall | 27% ± 39% | 0% ± 0% | 70% ± 40% |
| DEFEND precision | 6% ± 8% | - | 10% ± 5% |
| DEFEND right | 20% ± 17% | - | 74% ± 12% |
| DEFEND lead s (median) | 112.00 ± 37.25 | - | 126.94 ± 36.16 |
| REPASS recall | 0% | 0% | 0% |
| REPASS precision | 0% ± 0% | - | 0% ± 0% |
| CLOSING recall | 0% ± 1% | 0% ± 0% | 5% ± 3% |
| CLOSING precision | 11% | - | 29% ± 11% |
| alerts per race | 29.60 ± 6.37 | 41.60 ± 10.25 | 59.80 ± 22.18 |
| incident pass | - | - | - |

### closing_speed (seeds 6, 7, 8, 9, 10; target produced in 5/5)

| metric | built-in | dumb rule | Simply Clipping |
| --- | --- | --- | --- |
| energy MAE MJ | 0.95 ± 0.04 | - | 0.41 ± 0.02 |
| energy p90 MJ | 1.96 ± 0.06 | - | 1.13 ± 0.08 |
| MAE conf>=0.5 | 1.05 ± 0.11 | - | 0.35 ± 0.03 |
| within 0.5 MJ | 34% ± 2% | - | 71% ± 2% |
| confidence ECE | 28% ± 2% | - | 6% ± 2% |
| CLIP precision | 4% ± 0% | - | 65% ± 4% |
| CLIP recall | 35% ± 1% | - | 20% ± 1% |
| false CLIP in taper | 0% ± 0% | - | 0% ± 0% |
| CdA abs err straight % | - | - | 4.13 ± 0.11 |
| CdA abs err corner % | - | - | 3.98 ± 0.34 |
| CdA trap err straight % | - | - | - |
| ATTACK recall | 11% ± 16% | 100% ± 0% | 17% ± 24% |
| ATTACK precision | 10% ± 20% | 8% ± 8% | 12% ± 22% |
| ATTACK right | 14% ± 20% | 7% ± 2% | 19% ± 21% |
| ATTACK lead s (median) | 203.50 | 62.08 ± 63.41 | 35.50 |
| DEFEND recall | 42% ± 5% | 0% ± 0% | 91% ± 5% |
| DEFEND precision | 63% ± 10% | - | 60% ± 5% |
| DEFEND right | 87% ± 12% | - | 94% ± 7% |
| DEFEND lead s (median) | 39.48 ± 37.93 | - | 20.60 ± 3.72 |
| REPASS recall | 50% ± 50% | 0% ± 0% | 50% ± 50% |
| REPASS precision | 7% ± 13% | - | 1% ± 3% |
| CLOSING recall | 6% ± 3% | 0% ± 0% | 4% ± 2% |
| CLOSING precision | 27% ± 17% | - | 34% ± 20% |
| alerts per race | 36.60 ± 11.27 | 23.20 ± 4.96 | 53.80 ± 10.15 |
| incident pass | 0% ± 0% | 0% ± 0% | 0% ± 0% |

### normal (seeds 6, 7, 8, 9, 10; target produced in 5/5)

| metric | built-in | dumb rule | Simply Clipping |
| --- | --- | --- | --- |
| energy MAE MJ | 0.92 ± 0.03 | - | 0.36 ± 0.01 |
| energy p90 MJ | 1.87 ± 0.03 | - | 1.02 ± 0.03 |
| MAE conf>=0.5 | 0.98 ± 0.11 | - | 0.33 ± 0.03 |
| within 0.5 MJ | 34% ± 2% | - | 73% ± 1% |
| confidence ECE | 28% ± 1% | - | 7% ± 2% |
| CLIP precision | 4% ± 0% | - | 65% ± 4% |
| CLIP recall | 36% ± 1% | - | 20% ± 1% |
| false CLIP in taper | 0% ± 0% | - | 0% ± 0% |
| CdA abs err straight % | - | - | 3.69 ± 0.52 |
| CdA abs err corner % | - | - | 4.37 ± 0.50 |
| CdA trap err straight % | - | - | - |
| ATTACK recall | 75% ± 43% | 100% ± 0% | 0% ± 0% |
| ATTACK precision | 8% ± 8% | 6% ± 5% | 0% ± 0% |
| ATTACK right | 46% ± 7% | 32% ± 9% | 50% ± 29% |
| ATTACK lead s (median) | 146.46 ± 7.85 | 97.53 ± 46.00 | - |
| DEFEND recall | 39% ± 28% | 0% ± 0% | 89% ± 16% |
| DEFEND precision | 17% ± 20% | - | 8% ± 6% |
| DEFEND right | 84% ± 14% | - | 88% ± 12% |
| DEFEND lead s (median) | 173.88 ± 37.88 | - | 63.33 ± 42.46 |
| REPASS recall | - | - | - |
| REPASS precision | 0% ± 0% | - | 0% ± 0% |
| CLOSING recall | 2% ± 4% | 0% ± 0% | 6% ± 3% |
| CLOSING precision | 67% | - | 28% ± 11% |
| alerts per race | 37.80 ± 7.78 | 46.60 ± 7.79 | 30.40 ± 7.50 |
| incident pass | - | - | - |

### repass (seeds 6, 7, 8, 9, 10; target produced in 3/5)

| metric | built-in | dumb rule | Simply Clipping |
| --- | --- | --- | --- |
| energy MAE MJ | 0.97 ± 0.02 | - | 0.39 ± 0.01 |
| energy p90 MJ | 1.98 ± 0.03 | - | 1.08 ± 0.02 |
| MAE conf>=0.5 | 1.04 ± 0.13 | - | 0.34 ± 0.03 |
| within 0.5 MJ | 33% ± 1% | - | 72% ± 2% |
| confidence ECE | 27% ± 1% | - | 6% ± 2% |
| CLIP precision | 4% ± 0% | - | 65% ± 4% |
| CLIP recall | 35% ± 1% | - | 19% ± 1% |
| false CLIP in taper | 0% ± 0% | - | 0% ± 0% |
| CdA abs err straight % | - | - | 3.92 ± 0.22 |
| CdA abs err corner % | - | - | 4.67 ± 0.22 |
| CdA trap err straight % | - | - | - |
| ATTACK recall | 55% ± 20% | 74% ± 15% | 20% ± 7% |
| ATTACK precision | 26% ± 11% | 29% ± 9% | 36% ± 19% |
| ATTACK right | 29% ± 10% | 22% ± 13% | 51% ± 11% |
| ATTACK lead s (median) | 53.75 ± 36.07 | 87.00 ± 43.18 | 32.25 ± 33.90 |
| DEFEND recall | 60% ± 26% | 0% ± 0% | 74% ± 39% |
| DEFEND precision | 26% ± 16% | - | 16% ± 8% |
| DEFEND right | 65% ± 13% | - | 77% ± 18% |
| DEFEND lead s (median) | 76.60 ± 54.09 | - | 81.97 ± 32.43 |
| REPASS recall | 36% ± 31% | 0% ± 0% | 43% ± 26% |
| REPASS precision | 23% ± 21% | - | 18% ± 12% |
| CLOSING recall | 1% ± 3% | 0% ± 0% | 1% ± 1% |
| CLOSING precision | 31% | - | 38% ± 41% |
| alerts per race | 55.40 ± 15.25 | 42.80 ± 11.53 | 48.40 ± 16.21 |
| incident pass | 33% ± 47% | 0% ± 0% | 67% ± 47% |

### taper (seeds 6, 7, 8, 9, 10; target produced in 5/5)

| metric | built-in | dumb rule | Simply Clipping |
| --- | --- | --- | --- |
| energy MAE MJ | 1.28 ± 0.07 | - | 0.88 ± 0.05 |
| energy p90 MJ | 2.47 ± 0.05 | - | 1.85 ± 0.19 |
| MAE conf>=0.5 | 1.41 ± 0.10 | - | 0.84 ± 0.07 |
| within 0.5 MJ | 20% ± 4% | - | 38% ± 1% |
| confidence ECE | 18% ± 2% | - | 10% ± 2% |
| CLIP precision | 4% ± 0% | - | 53% ± 5% |
| CLIP recall | 37% ± 1% | - | 19% ± 1% |
| false CLIP in taper | 0% ± 0% | - | 0% ± 0% |
| CdA abs err straight % | - | - | 2.79 ± 0.57 |
| CdA abs err corner % | - | - | 2.85 ± 0.35 |
| CdA trap err straight % | - | - | - |
| ATTACK recall | 40% ± 37% | 83% ± 21% | 47% ± 32% |
| ATTACK precision | 10% ± 13% | 9% ± 4% | 10% ± 5% |
| ATTACK right | 38% ± 26% | 28% ± 8% | 45% ± 14% |
| ATTACK lead s (median) | 92.83 ± 41.12 | 129.45 ± 37.02 | 78.69 ± 38.95 |
| DEFEND recall | 25% ± 25% | 0% ± 0% | 38% ± 38% |
| DEFEND precision | 5% ± 10% | - | 5% ± 11% |
| DEFEND right | 47% ± 2% | - | 69% ± 7% |
| DEFEND lead s (median) | 55.50 | - | 3.75 |
| REPASS recall | 0% | 0% | 0% |
| REPASS precision | 0% ± 0% | - | 0% ± 0% |
| CLOSING recall | 2% ± 2% | 0% ± 0% | 11% ± 5% |
| CLOSING precision | 10% ± 12% | - | 33% ± 11% |
| alerts per race | 31.00 ± 5.73 | 29.80 ± 3.06 | 51.20 ± 6.71 |
| incident pass | - | - | - |

## TUNE SET (seeds 1-5)

### battles (seeds 1, 2, 3, 4, 5; target produced in 5/5)

| metric | built-in | dumb rule | Simply Clipping |
| --- | --- | --- | --- |
| energy MAE MJ | 0.80 ± 0.01 | - | 0.55 ± 0.09 |
| energy p90 MJ | 1.69 ± 0.03 | - | 1.35 ± 0.15 |
| MAE conf>=0.5 | 0.94 ± 0.04 | - | 0.54 ± 0.09 |
| within 0.5 MJ | 39% ± 1% | - | 57% ± 7% |
| confidence ECE | 33% ± 1% | - | 12% ± 6% |
| CLIP precision | 6% ± 0% | - | 65% ± 3% |
| CLIP recall | 41% ± 1% | - | 27% ± 1% |
| false CLIP in taper | 1% ± 0% | - | 1% ± 0% |
| CdA abs err straight % | - | - | 3.83 ± 0.42 |
| CdA abs err corner % | - | - | 7.32 ± 0.29 |
| CdA trap err straight % | - | - | - |
| ATTACK recall | 62% ± 14% | 84% ± 5% | 4% ± 4% |
| ATTACK precision | 29% ± 5% | 28% ± 7% | 16% ± 18% |
| ATTACK right | 46% ± 12% | 36% ± 10% | 72% ± 13% |
| ATTACK lead s (median) | 97.00 ± 24.97 | 98.93 ± 12.76 | 79.08 ± 60.34 |
| DEFEND recall | 53% ± 19% | 0% ± 0% | 76% ± 3% |
| DEFEND precision | 34% ± 17% | - | 24% ± 11% |
| DEFEND right | 48% ± 13% | - | 67% ± 18% |
| DEFEND lead s (median) | 99.00 ± 40.62 | - | 91.10 ± 40.03 |
| REPASS recall | 53% ± 45% | 0% ± 0% | 40% ± 49% |
| REPASS precision | 28% ± 37% | - | 8% ± 10% |
| CLOSING recall | 0% ± 0% | 0% ± 0% | 4% ± 3% |
| CLOSING precision | - | - | 10% ± 3% |
| alerts per race | 71.60 ± 8.78 | 61.60 ± 7.39 | 84.60 ± 21.09 |
| incident pass | - | - | - |

### cda_trap (seeds 1, 2, 3, 4, 5; target produced in 5/5)

| metric | built-in | dumb rule | Simply Clipping |
| --- | --- | --- | --- |
| energy MAE MJ | 0.84 ± 0.03 | - | 0.58 ± 0.02 |
| energy p90 MJ | 1.89 ± 0.07 | - | 1.62 ± 0.07 |
| MAE conf>=0.5 | 0.78 ± 0.08 | - | 0.39 ± 0.04 |
| within 0.5 MJ | 42% ± 1% | - | 62% ± 2% |
| confidence ECE | 34% ± 1% | - | 4% ± 2% |
| CLIP precision | 4% ± 0% | - | 52% ± 3% |
| CLIP recall | 37% ± 1% | - | 20% ± 1% |
| false CLIP in taper | 1% ± 0% | - | 2% ± 0% |
| CdA abs err straight % | - | - | 3.97 ± 0.08 |
| CdA abs err corner % | - | - | 3.91 ± 0.42 |
| CdA trap err straight % | - | - | 3.89 ± 0.47 |
| ATTACK recall | 57% ± 42% | 100% ± 0% | 41% ± 29% |
| ATTACK precision | 8% ± 10% | 7% ± 8% | 8% ± 13% |
| ATTACK right | 79% ± 19% | 64% ± 14% | 95% ± 5% |
| ATTACK lead s (median) | 150.00 ± 17.25 | 94.54 ± 64.56 | 88.81 ± 38.19 |
| DEFEND recall | 62% ± 41% | 0% ± 0% | 75% ± 43% |
| DEFEND precision | 18% ± 19% | - | 13% ± 15% |
| DEFEND right | 20% ± 14% | - | 70% ± 17% |
| DEFEND lead s (median) | 126.29 ± 39.51 | - | 185.67 ± 21.16 |
| REPASS recall | - | - | - |
| REPASS precision | 0% ± 0% | - | 0% ± 0% |
| CLOSING recall | 0% ± 0% | 0% ± 0% | 3% ± 2% |
| CLOSING precision | - | - | 14% ± 7% |
| alerts per race | 35.00 ± 14.60 | 45.40 ± 6.53 | 63.00 ± 23.04 |
| incident pass | - | - | - |

### closing_speed (seeds 1, 2, 3, 4, 5; target produced in 5/5)

| metric | built-in | dumb rule | Simply Clipping |
| --- | --- | --- | --- |
| energy MAE MJ | 0.96 ± 0.03 | - | 0.38 ± 0.05 |
| energy p90 MJ | 1.98 ± 0.04 | - | 1.01 ± 0.13 |
| MAE conf>=0.5 | 1.06 ± 0.04 | - | 0.33 ± 0.06 |
| within 0.5 MJ | 33% ± 1% | - | 73% ± 5% |
| confidence ECE | 28% ± 2% | - | 7% ± 5% |
| CLIP precision | 4% ± 0% | - | 64% ± 2% |
| CLIP recall | 35% ± 0% | - | 20% ± 1% |
| false CLIP in taper | 0% ± 0% | - | 0% ± 0% |
| CdA abs err straight % | - | - | 3.97 ± 0.49 |
| CdA abs err corner % | - | - | 3.79 ± 0.20 |
| CdA trap err straight % | - | - | - |
| ATTACK recall | 0% ± 0% | 100% ± 0% | 33% ± 47% |
| ATTACK precision | 0% ± 0% | 4% ± 4% | 8% ± 14% |
| ATTACK right | 10% ± 20% | 10% ± 3% | 71% ± 18% |
| ATTACK lead s (median) | - | 152.25 ± 37.25 | 35.50 |
| DEFEND recall | 38% ± 15% | 0% ± 0% | 89% ± 17% |
| DEFEND precision | 55% ± 21% | - | 56% ± 18% |
| DEFEND right | 92% ± 6% | - | 94% ± 3% |
| DEFEND lead s (median) | 20.05 ± 4.61 | - | 25.58 ± 6.29 |
| REPASS recall | 100% | 0% | 100% |
| REPASS precision | 2% ± 4% | - | 1% ± 2% |
| CLOSING recall | 4% ± 2% | 0% ± 0% | 4% ± 2% |
| CLOSING precision | 39% ± 4% | - | 25% ± 7% |
| alerts per race | 38.60 ± 12.18 | 26.20 ± 4.07 | 66.20 ± 10.24 |
| incident pass | 0% ± 0% | 0% ± 0% | 0% ± 0% |

### normal (seeds 1, 2, 3, 4, 5; target produced in 5/5)

| metric | built-in | dumb rule | Simply Clipping |
| --- | --- | --- | --- |
| energy MAE MJ | 0.91 ± 0.01 | - | 0.34 ± 0.05 |
| energy p90 MJ | 1.87 ± 0.03 | - | 0.94 ± 0.15 |
| MAE conf>=0.5 | 1.01 ± 0.07 | - | 0.32 ± 0.05 |
| within 0.5 MJ | 34% ± 1% | - | 75% ± 5% |
| confidence ECE | 28% ± 1% | - | 8% ± 5% |
| CLIP precision | 4% ± 0% | - | 66% ± 3% |
| CLIP recall | 36% ± 1% | - | 19% ± 1% |
| false CLIP in taper | 0% ± 0% | - | 0% ± 0% |
| CdA abs err straight % | - | - | 3.50 ± 0.76 |
| CdA abs err corner % | - | - | 4.40 ± 0.18 |
| CdA trap err straight % | - | - | - |
| ATTACK recall | 77% ± 20% | 87% ± 16% | 13% ± 27% |
| ATTACK precision | 11% ± 8% | 9% ± 4% | 13% ± 27% |
| ATTACK right | 37% ± 15% | 36% ± 14% | 40% ± 24% |
| ATTACK lead s (median) | 109.80 ± 45.83 | 114.13 ± 50.58 | 224.88 |
| DEFEND recall | 67% ± 24% | 0% ± 0% | 83% ± 24% |
| DEFEND precision | 10% ± 11% | - | 9% ± 10% |
| DEFEND right | 66% ± 19% | - | 84% ± 12% |
| DEFEND lead s (median) | 148.25 ± 49.44 | - | 93.88 ± 18.41 |
| REPASS recall | - | - | - |
| REPASS precision | 0% ± 0% | - | 0% ± 0% |
| CLOSING recall | 0% ± 0% | 0% ± 0% | 3% ± 2% |
| CLOSING precision | 0% | - | 19% ± 6% |
| alerts per race | 39.40 ± 7.61 | 43.20 ± 7.63 | 27.40 ± 2.65 |
| incident pass | - | - | - |

### repass (seeds 1, 2, 3, 4, 5; target produced in 3/5)

| metric | built-in | dumb rule | Simply Clipping |
| --- | --- | --- | --- |
| energy MAE MJ | 0.97 ± 0.02 | - | 0.37 ± 0.05 |
| energy p90 MJ | 1.98 ± 0.04 | - | 0.99 ± 0.14 |
| MAE conf>=0.5 | 1.08 ± 0.04 | - | 0.33 ± 0.05 |
| within 0.5 MJ | 33% ± 1% | - | 74% ± 5% |
| confidence ECE | 28% ± 1% | - | 7% ± 4% |
| CLIP precision | 4% ± 0% | - | 63% ± 3% |
| CLIP recall | 36% ± 1% | - | 19% ± 0% |
| false CLIP in taper | 0% ± 0% | - | 0% ± 0% |
| CdA abs err straight % | - | - | 3.87 ± 0.43 |
| CdA abs err corner % | - | - | 4.47 ± 0.29 |
| CdA trap err straight % | - | - | - |
| ATTACK recall | 71% ± 12% | 85% ± 12% | 33% ± 13% |
| ATTACK precision | 24% ± 15% | 22% ± 10% | 19% ± 5% |
| ATTACK right | 40% ± 15% | 27% ± 14% | 72% ± 6% |
| ATTACK lead s (median) | 109.18 ± 37.89 | 101.68 ± 24.39 | 94.80 ± 52.96 |
| DEFEND recall | 52% ± 20% | 0% ± 0% | 62% ± 25% |
| DEFEND precision | 29% ± 12% | - | 18% ± 7% |
| DEFEND right | 79% ± 9% | - | 90% ± 7% |
| DEFEND lead s (median) | 87.53 ± 55.63 | - | 75.90 ± 48.80 |
| REPASS recall | 33% ± 28% | 0% ± 0% | 53% ± 41% |
| REPASS precision | 22% ± 14% | - | 15% ± 9% |
| CLOSING recall | 0% ± 0% | 0% ± 0% | 2% ± 2% |
| CLOSING precision | 0% | - | 7% ± 9% |
| alerts per race | 48.80 ± 9.26 | 47.00 ± 7.48 | 48.60 ± 10.50 |
| incident pass | 0% ± 0% | 0% ± 0% | 50% ± 50% |

### taper (seeds 1, 2, 3, 4, 5; target produced in 5/5)

| metric | built-in | dumb rule | Simply Clipping |
| --- | --- | --- | --- |
| energy MAE MJ | 1.28 ± 0.08 | - | 0.87 ± 0.04 |
| energy p90 MJ | 2.45 ± 0.07 | - | 1.84 ± 0.14 |
| MAE conf>=0.5 | 1.39 ± 0.13 | - | 0.84 ± 0.07 |
| within 0.5 MJ | 20% ± 3% | - | 38% ± 1% |
| confidence ECE | 18% ± 2% | - | 9% ± 3% |
| CLIP precision | 4% ± 0% | - | 54% ± 5% |
| CLIP recall | 37% ± 1% | - | 19% ± 1% |
| false CLIP in taper | 0% ± 0% | - | 0% ± 0% |
| CdA abs err straight % | - | - | 2.56 ± 0.25 |
| CdA abs err corner % | - | - | 2.71 ± 0.33 |
| CdA trap err straight % | - | - | - |
| ATTACK recall | 42% ± 43% | 92% ± 14% | 67% ± 41% |
| ATTACK precision | 8% ± 12% | 5% ± 3% | 8% ± 7% |
| ATTACK right | 43% ± 17% | 26% ± 11% | 46% ± 6% |
| ATTACK lead s (median) | 59.13 ± 55.38 | 102.81 ± 42.64 | 110.04 ± 73.01 |
| DEFEND recall | 56% ± 42% | 0% ± 0% | 89% ± 16% |
| DEFEND precision | 3% ± 4% | - | 4% ± 4% |
| DEFEND right | 56% ± 7% | - | 62% ± 12% |
| DEFEND lead s (median) | 30.75 ± 14.75 | - | 65.79 ± 47.43 |
| REPASS recall | - | - | - |
| REPASS precision | 0% ± 0% | - | 0% ± 0% |
| CLOSING recall | 1% ± 1% | 0% ± 0% | 10% ± 4% |
| CLOSING precision | 10% ± 13% | - | 37% ± 8% |
| alerts per race | 30.40 ± 6.89 | 31.00 ± 2.61 | 53.40 ± 4.88 |
| incident pass | - | - | - |

## REAL RACE — 2026 Japanese Grand Prix (Simply Clipping SC-5)

Hand-written; `write_results` keeps this section when it rewrites the tables.
Data: OpenF1 session 11253 (Suzuka, 29 March 2026: **pre-Miami** rules, while
Simply Clipping's constants follow the post-Miami set), all 22 cars:
`car_data` (~3.7 Hz), `location`, `laps`; cached in `data/openf1_cache/`.

```powershell
python -m simply_clipping.real_data --session 11253 --our NOR --out data/sc_real/jpn2026_nor
python -m simply_clipping.real_data --session 11253 --our BEA --out data/sc_real/jpn2026_bea
```

A real race has no team data for "us": Our Car's battery is Simply Clipping's own
estimate of that car from its public feed, not an exact value. Race times are
seconds from lap 1's start (05:14:02 UTC). Config: `sc-v1`.

### a) Norris passes Hamilton, clips, Hamilton re-passes → RE-PASS RISK (Our Car = NOR)

The data (OpenF1 `overtakes`) has the pattern twice, laps 47 and 50:

| NOR passes HAM | RE-PASS RISK (car_b HAM) | HAM re-passes | Lead time | Evidence |
| --- | --- | --- | --- | --- |
| 06:32:54.8 (t 4732.7 s, lap 47) | t 4732.5 s | 06:33:09.7 (t 4747.6 s) | **15.1 s** | NOR est 0.39 MJ (< 1.0), HAM est 0.37 MJ, gap 0.27 s, 600 m+ straight ahead |
| 06:37:37.3 (t 5015.3 s, lap 50) | t 5015.0 s | 06:37:57.1 (t 5035.0 s) | **20.0 s** | NOR est 0.41 MJ, HAM est 0.31 MJ, gap 0.42 s |

The clip shows in the raw data: on the straight after each pass NOR stays flat at
289-294 km/h (lap 47) and ~304 km/h (lap 50) at full throttle while HAM
accelerates to 329-336 km/h; Simply Clipping marks NOR CLIP there. Both alerts
fire at the pass (the rule needs "we passed in the last 15 s"), 15-20 s before
the re-pass. **Result: the incident is caught, both times.**

### b) Lap 22: Bearman closing on Colapinto before Spoon → CLOSING-SPEED RISK (Our Car = BEA)

Race control: yellow in sectors 20-21 at 05:47:54 UTC (t ≈ 2032 s), Safety
Car at 05:48:11, "TURN 13 INCIDENT INVOLVING CARS 43 (COL) AND 87 (BEA)". In the
data:

- COL is flat at 261-262 km/h at full throttle from t 2021 to 2026 s (no deploy,
  consistent with a car out of energy before Spoon), then brakes (262 → 154 km/h).
- **BEA's `car_data` is not usable here:** its values are held (repeated samples)
  and read exactly 262 km/h with the brake flag set from t 2020.4 to 2027.8 s,
  then 93 km/h.
- BEA's **positions** show the closing: 44 m behind COL at t 2021, 22.5 m at
  2024, 10.8 m at 2025, 1.1 m at 2026 s; closing speed 35-42 km/h over the last
  two seconds.

Simply Clipping reads speed from `car_data`; there both cars are at 262 km/h, so
Δv ≈ 0 and **no CLOSING-SPEED RISK fires**. The incident is real but is visible
only in the position data, not in BEA's speed channel. Honest result: **not
caught**; a speed derived from positions (not part of the RADAR input) would be
needed, and even then ~35-42 km/h sits at the 40 km/h threshold.

### Whole race

NOR 115 alerts (ATTACK 51, DEFEND 37, RE-PASS 25, CLOSING 2), BEA 118 (53 / 33 /
26 / 6): above the 100-per-race flag, because Our Car's battery is estimated (it
reads near empty often, which fires own-battery DEFEND and RE-PASS).
