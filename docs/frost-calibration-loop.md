# Frost Risk Model Calibration Loop Architecture

This document describes the planned empirical calibration loop for the Frost Risk module once sufficient field ground-truth observations are accumulated in the `orchard_observations` table.

---

## 1. Objective and Evidence Level Transition

The Frost Risk engine operates initially at **Evidence Level C** (`thresholds_verified: false`), using conservative published baseline thresholds (`published_v1`, Hokmabadi 2010/2011).

The calibration loop provides the empirical bridge to transition the engine to **Evidence Level B** (`thresholds_verified: true`), replacing provisional literature figures with statistically calibrated regional threshold curves and verified terrain pooling constants.

---

## 2. Ingested Ground-Truth Data

The `orchard_observations` table collects on-farm observational records:
- **Spatial context:** `orchard_id` (polygon centroid, elevation $z_{\text{site}}$, local topographic indices).
- **Temporal context:** `observation_date` (local night window 18:00 to 09:00).
- **Phenological stage:** Developmental stage (`dormant`, `bud_burst`, `early_bloom`, `full_bloom`, `fruit_set`).
- **Thermal exposure:** In-situ canopy/surface minimum temperature ($T_{\min, \text{observed}}$).
- **Biological response:** Categorical damage severity (`none`, `light`, `moderate`, `severe`, `total`) and descriptive injury notes (`damage_observed_fa`).

---

## 3. Calibration Procedures

Once a statistically sufficient sample ($N \ge 30$ freezing events per phenological stage across multiple orchards) is logged, the offline calibration pipeline performs the following steps:

### A. Microclimate Pooling & Lapse Rate Tuning
1. For each radiative frost night (clear skies, calm wind $\le 1.5\,\text{m/s}$):
   $$\Delta T_{\text{observed}} = T_{\text{cell, GFS}} - T_{\min, \text{observed}}$$
2. Regress $\Delta T_{\text{observed}}$ against:
   - Elevation delta $\Delta z = z_{\text{site}} - z_{\text{cell}}$ to estimate regional lapse rate $\Gamma_{\text{eff}}$.
   - Topographic index `pooling_risk_proxy` to calibrate maximum stagnation bump ($\Delta T_{\max, \text{bump}}$) and proxy activation threshold.
3. Fit wind damping coefficients against observed turbulent dissipation at varying anemometer speeds ($1.5 \dots 4.0\,\text{m/s}$).

### B. Phenological Critical Mortality Curve Fitting
For each phenological stage, model the probability of freeze injury as a logistic function of minimum exposure temperature $T$ and continuous sub-threshold duration $H$:
$$P(\text{Damage} \ge \text{Tier} \mid T, H) = \frac{1}{1 + \exp\left(-\frac{T - T_{50}}{\beta_T} - \gamma H\right)}$$

From the fitted logistic regression parameters:
- **$T_{c10}$ (10% damage / advisory threshold):** Temperature at which $P(\text{light injury}) = 0.10$.
- **$T_{c90}$ (90% damage / critical freeze threshold):** Temperature at which $P(\text{severe necrosis}) = 0.90$.
- **Duration escalation rules:** Critical continuous exposure duration $H^*$ at which odds of mortality double.

### C. Orchard Management Protective Factor Verification
Evaluate the empirical thermal benefit of soil management practices (firm, moist, weed-free soil vs cultivated/dry soil) and pre-freeze irrigation:
$$\Delta T_{\text{protection}} = T_{\min, \text{managed}} - T_{\min, \text{unmanaged}}$$
If empirical $\Delta T_{\text{protection}}$ statistically differs from $0.0^\circ\text{C}$ with $p < 0.01$, update the conservative $1.0^\circ\text{C}$ cap in `config/frost_factors.yaml`.

---

## 4. Verification & Deployment Gate

Before deploying calibrated parameters to production:
1. **Out-of-sample Cross-Validation:** Evaluate classification skill (Brier score, ROC-AUC, False Alarm Ratio) on a held-out test split of observation nights.
2. **Agronomic Review:** Review by regional pistachio physiology specialists.
3. **Configuration Release:**
   - Commit calibrated values to a new threshold set `calibrated_v1` in `config/frost_thresholds.yaml`.
   - Update `status: calibrated`, `verified: true`, `source: "Iran Pistachio In-Situ Observation Network"`.
   - Set `evidence_level: "B"` in response contracts.
