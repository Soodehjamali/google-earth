# Frost Risk Decision Table & Duration Engine Specification

This document defines the formal decision table and mathematical specification for the Phase 3 Frost Risk Assessment Engine.

---

## 1. Sourced Agronomic Thresholds & References

In strict accordance with the sourced literature recorded in `docs/frost-sources-v1.md`, only published and cited numbers are used as damage thresholds. Sources `[S1]` and `[S2]` share the same author (H. Hokmabadi) and are not independent confirmations.

| Phenological Stage | Sourced Critical Temperature ($T_{\text{crit}}$) | Source | Published Duration Rule | Source | Conflicting Published Value |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Dormant** (`dormant`) | *Null* (placeholder $-15.0^\circ\text{C}$) | S1/S2 no data | *Null* | — | — |
| **Unopened Bud** (`bud_burst` / flower buds) | $-4.0^\circ\text{C}$ | S2; S1 p. 72 | $\le -4.0^\circ\text{C}$ for $\ge 2.0\text{ h} \implies \text{Critical}$<br>$-4.0$ to $-6.0^\circ\text{C}$ for $\ge 6.0\text{ h} \implies \text{Critical (Severe)}$ | S1 p. 72 | — |
| **Opening Bud** (`bud_burst`) | $-2.0^\circ\text{C}$ | S2 | $\le -4.0^\circ\text{C}$ for $\ge 2.0\text{ h} \implies \text{Critical}$ | S1 p. 72 | — |
| **Bloom** (`early_bloom`, `full_bloom`) | $-1.7^\circ\text{C}$ | Hokmabadi 2010 CIHEAM (Options Méditerranéennes A94, p. 77) | *Null* (no duration data published) | — | $+2.0^\circ\text{C}$ in Hokmabadi 2011 Iran Pistachio Association (conflicting; NOT used as damage threshold) |
| **Fruit Set** (`fruit_set`) | $-2.0^\circ\text{C}$ | S2 | *Null* (no duration data published) | — | — |

> [!IMPORTANT]
> Where a stage lacks published duration data (`duration_rules: null`), duration does NOT escalate risk categories. The system clearly discloses to the user:
> *"برای این مرحله داده منتشرشده‌ای برای مدت ماندن زیر آستانه وجود ندارد؛ دسته‌بندی فقط بر اساس دما است"*

---

## 2. Interval-Based Duration Computation

### 2.1 Sample-Hours vs Interval Duration
- NOAA GFS forecast series are delivered as discrete timesteps $t_0, t_1, \dots, t_K$.
- In the native hourly horizon ($0 \le \text{lead\_hours} \le 120$), step cadence is exactly $\Delta t = 1.0\text{ h}$.
- Each hourly step $t_i$ represents an exposure interval $[t_i - 0.5\text{ h}, t_i + 0.5\text{ h}]$ of duration $\Delta t = 1.0\text{ h}$.
- A contiguous run of $M$ hourly steps below a threshold $T_{\text{ref}}$ represents an exposure interval of $M \times 1.0 = M\text{ hours}$.

### 2.2 Continuous Run Identification
- A **continuous run** is defined as a maximal consecutive sub-sequence of timesteps $[t_a, \dots, t_b]$ where $t_{k+1} - t_k \le 1.5\text{ h}$ and $T_k \le T_{\text{ref}}$ for all $k \in [a, b]$.
- **Longest Continuous Run:** The continuous run with maximum duration $M = (b - a + 1)\text{ hours}$.
- **Run Timing:** Reported in local `Asia/Tehran` time (Iran Standard Time, UTC+3:30) as:
  `longest_run_start_local` ($t_a$) and `longest_run_end_local` ($t_b$).
- **Minimum Temperature Timestamp:** The exact timestamp $t_{\min}$ of the minimum effective temperature in `Asia/Tehran` time.

### 2.3 Nominal vs Pessimistic Duration
- **Nominal Run:** Evaluated on effective minimum temperature $T_{\text{nom}, i} = T_{\text{forecast}, i} - \text{pooling\_bump}_i$.
- **Pessimistic Run:** Evaluated on conservative lower bound $T_{\text{pess}, i} = T_{\text{nom}, i} - \sigma_{\text{total}, i}$.
- The system reports both nominal and pessimistic total exposure hours and longest continuous run hours.

### 2.4 Cadence Gating (Beyond 120 h)
- For forecast timesteps beyond 120 hours, NOAA GFS native cadence is 3-hourly ($\Delta t = 3.0\text{ h}$).
- Because 3-hourly sampling cannot resolve 1-hour or 2-hour duration thresholds without synthetic interpolation (which is forbidden), duration is explicitly marked:
  `duration_resolvable: false` ("not resolvable").
- Risk categories beyond 120h are evaluated purely on temperature extrema and flagged with `cadence_coarse: true`.

---

## 3. Risk Category Decision Table

The engine maps all evaluations into the platform's standardized categories: `none`, `watch`, `warning`, `critical`.

### 3.1 Decision Matrix (Hourly Data $\le 120\text{ h}$)

| Nominal Min Temp ($T_{\text{min, nom}}$) | Pessimistic Min Temp ($T_{\text{min, pess}}$) | Longest Continuous Run ($M_{\text{nom}}$) | Stage Duration Rule State | Assigned Severity Category | Notes & UI Flags |
| :--- | :--- | :--- | :--- | :--- | :--- |
| $> T_{\text{ref}}$ | $> T_{\text{ref}}$ | $0.0\text{ h}$ | Any | **`none`** | Safe baseline; no frost risk. |
| $> T_{\text{ref}}$ | $\le T_{\text{ref}}$ | Nominal $0\text{ h}$, Pessimistic $> 0\text{ h}$ | Any | **`watch`** | **Pessimistic-only escalation rule:** Pessimistic run may ONLY raise risk to `watch`, never to `warning` or `critical`. |
| $\le T_{\text{ref}}$ | $\le T_{\text{ref}}$ | $< 1.0\text{ h}$ (e.g. $0.9\text{ h}$) | Configured ($T_{\text{ref}} \le -4^\circ\text{C}$) | **`watch`** | Brief dip below threshold stays `watch` (`short_dip: true`). |
| $\le T_{\text{ref}}$ | $\le T_{\text{ref}}$ | $1.0\text{ h} \le M < 2.0\text{ h}$ (e.g. $1.0\text{ h}, 1.9\text{ h}$) | Configured ($T_{\text{ref}} \le -4^\circ\text{C}$) | **`warning`** | Sustained cold exposure below critical threshold. |
| $\le T_{\text{ref}}$ | $\le T_{\text{ref}}$ | $2.0\text{ h} \le M < 6.0\text{ h}$ (e.g. $2.0\text{ h}, 2.1\text{ h}, 5.9\text{ h}$) | Configured ($T_{\text{ref}} \le -4^\circ\text{C}$) | **`critical`** | **S1 p. 72 rule:** $\le -4^\circ\text{C}$ for $\ge 2\text{ h}$ causes severe floral bud necrosis. |
| $\le T_{\text{ref}}$ | $\le T_{\text{ref}}$ | $\ge 6.0\text{ h}$ (e.g. $6.0\text{ h}$) | Configured ($T_{\text{ref}} \le -4^\circ\text{C}$) | **`critical`** | **S1 p. 72 rule:** $-4$ to $-6^\circ\text{C}$ for $\sim 6\text{ h}$ causes complete pistil necrosis. |
| $\le T_{\text{ref}}$ | $\le T_{\text{ref}}$ | Any | `null` (e.g. Bloom, Fruit) | **`warning`** (or **`critical`** if $T \le T_{\text{ref}} - 2.0^\circ$) | **Null duration rule:** Category based on temperature only. UI renders null duration notice. |

### 3.2 Decision Matrix (3-Hourly Data $> 120\text{ h}$)

| Nominal Min Temp ($T_{\text{min, nom}}$) | Pessimistic Min Temp ($T_{\text{min, pess}}$) | Duration Resolvability | Assigned Severity Category | Notes & UI Flags |
| :--- | :--- | :--- | :--- | :--- |
| $> T_{\text{ref}}$ | $> T_{\text{ref}}$ | Not resolvable | **`none`** | Safe baseline. |
| $> T_{\text{ref}}$ | $\le T_{\text{ref}}$ | Not resolvable | **`watch`** | Pessimistic uncertainty envelope touches threshold. |
| $\le T_{\text{ref}}$ and $> T_{\text{ref}} - 2.0^\circ\text{C}$ | $\le T_{\text{ref}}$ | Not resolvable | **`warning`** | Temperature alone sets category; duration flagged not resolvable. |
| $\le T_{\text{ref}} - 2.0^\circ\text{C}$ | $\le T_{\text{ref}}$ | Not resolvable | **`critical`** | Severe freeze event; duration flagged not resolvable. |

---

## 4. UI Representation & Disclosures

1. **Duration Card Metric:**
   - English: `"N h below X °C (longest continuous M h, from HH:MM to HH:MM)"`
   - Persian: `"N ساعت زیر X درجه (طولانی‌ترین دوره پیوسته M ساعت، از HH:MM تا HH:MM)"`
2. **Rule Explanation & Citation:**
   - Active S1 Rule: *"آستانه تداوم: دمای ۴- درجه یا کمتر به مدت حداقل ۲ ساعت منجر به سطح بحرانی خسارت جوانه می‌شود (منبع: حکم‌آبادی ۱۳۸۹، صفحه ۷۲ [S1])."*
   - Null Rule Notice: *"برای این مرحله داده منتشرشده‌ای برای مدت ماندن زیر آستانه وجود ندارد؛ دسته‌بندی فقط بر اساس دما است."*
   - Conflicting S2 Value Notice: *"مقدار متعارض منتشرشده برای مرحله گلدهی: ۲+ درجه سانتی‌گراد (حکم‌آبادی ۱۳۹۰، انجمن پسته ایران [S2])؛ این مقدار به عنوان آستانه خسارت استفاده نشده است."*
