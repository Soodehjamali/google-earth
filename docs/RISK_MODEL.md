# Agricultural Risk Model

> The risk score is a transparent, explainable composite indicator. Every component is documented with its formula, weight, and normalization method.

---

## Overview

```
Agricultural Risk Score = Σ (component_weight × component_score)
```

- **Range**: 0–100
- **Interpretation**: Higher score = higher risk

---

## Components

### 1. Vegetation Stress (Weight: 0.30)

**Data Source**: Sentinel-2 NDVI

**Normalization**:
```
vegetation_score = (1 - (NDVI_current - NDVI_min) / (NDVI_baseline - NDVI_min)) × 100
```

Where:
- `NDVI_current` = Current period mean NDVI
- `NDVI_baseline` = 5-year mean NDVI for same period (if available)
- `NDVI_min` = Theoretical minimum (0.0 for bare soil)

**Fallback** (no baseline):
```
vegetation_score = (1 - NDVI_current / 0.7) × 100
```
(Clamped to 0–100)

| Score Range | Status |
|-------------|--------|
| 0–25 | Healthy vegetation |
| 25–50 | Minor stress detected |
| 50–75 | Moderate stress |
| 75–100 | Severe stress |

---

### 2. Water Stress (Weight: 0.25)

**Data Source**: ERA5 precipitation + soil moisture (or Sentinel-2 NDWI)

**Normalization**:
```
water_score = (1 - precipitation_percentile / 100) × 100
```

Where `precipitation_percentile` is the percentile of current precipitation relative to historical distribution.

**Combined with soil moisture** (if available):
```
water_score = 0.6 × precipitation_stress + 0.4 × soil_moisture_stress
```

| Score Range | Status |
|-------------|--------|
| 0–25 | Adequate water |
| 25–50 | Mild water deficit |
| 50–75 | Moderate water stress |
| 75–100 | Severe water stress |

---

### 3. Rainfall Anomaly (Weight: 0.20)

**Data Source**: ERA5 total precipitation

**Calculation**:
```
rainfall_anomaly = (precipitation_current - precipitation_historical_mean) / precipitation_historical_std
rainfall_score = max(0, min(100, 50 - rainfall_anomaly × 25))
```

| Anomaly | Score | Interpretation |
|---------|-------|---------------|
| < -2σ | 100 | Severe drought |
| -2σ to -1σ | 75 | Moderate drought |
| -1σ to +1σ | 50 | Normal |
| +1σ to +2σ | 25 | Above normal |
| > +2σ | 0 | Excess rainfall |

---

### 4. Temperature Anomaly (Weight: 0.15)

**Data Source**: ERA5 2m temperature

**Calculation**:
```
temp_anomaly = (temperature_current - temperature_historical_mean) / temperature_historical_std
temperature_score = max(0, min(100, 50 + |temp_anomaly| × 25))
```

Note: Both heat and cold extremes increase the score.

| Anomaly | Score | Interpretation |
|---------|-------|---------------|
| < -2σ | 100 | Severe cold stress |
| -2σ to -1σ | 75 | Moderate cold |
| -1σ to +1σ | 50 | Normal range |
| +1σ to +2σ | 75 | Moderate heat |
| > +2σ | 100 | Severe heat stress |

---

### 5. Soil Moisture Stress (Weight: 0.10)

**Data Source**: ERA5-Land soil moisture (0-7cm) or Sentinel-2 NDMI

**Normalization**:
```
soil_score = (1 - soil_moisture_current / soil_moisture_capacity) × 100
```

If no soil moisture data available, use NDMI as proxy:
```
soil_score = (1 - NDMI_current) × 100
```

| Score Range | Status |
|-------------|--------|
| 0–25 | Adequate soil moisture |
| 25–50 | Mild deficit |
| 50–75 | Moderate deficit |
| 75–100 | Severe deficit |

---

## Overall Score Calculation

```python
risk_score = (
    0.30 * vegetation_score +
    0.25 * water_score +
    0.20 * rainfall_score +
    0.15 * temperature_score +
    0.10 * soil_score
)
```

### Risk Levels

| Score | Level | Color | Recommendation |
|-------|-------|-------|---------------|
| 0–20 | Low | 🟢 Green | No immediate action needed |
| 20–40 | Moderate-Low | 🟡 Yellow-Green | Monitor conditions |
| 40–60 | Moderate | 🟡 Yellow | Plan potential interventions |
| 60–80 | High | 🟠 Orange | Active monitoring recommended |
| 80–100 | Critical | 🔴 Red | Urgent field inspection recommended |

---

## Missing Data Handling

When a component's data is unavailable:

1. **Redistribute weight** proportionally to available components
2. **Document** which components were included/excluded
3. **Report confidence level** based on data availability

```python
# Example: if water_score is unavailable
available_weights = [0.30, 0.20, 0.15, 0.10]  # vegetation, rainfall, temp, soil
total_weight = sum(available_weights)
normalized_weights = [w / total_weight for w in available_weights]

risk_score = sum(w * s for w, s in zip(normalized_weights, available_scores))
```

---

## Configuration

Weights and thresholds are configurable via a risk configuration object:

```python
RISK_CONFIG = {
    "components": {
        "vegetation": {"weight": 0.30, "threshold_healthy": 25, "threshold_stress": 75},
        "water": {"weight": 0.25, "threshold_healthy": 25, "threshold_stress": 75},
        "rainfall": {"weight": 0.20, "threshold_healthy": 25, "threshold_stress": 75},
        "temperature": {"weight": 0.15, "threshold_healthy": 25, "threshold_stress": 75},
        "soil": {"weight": 0.10, "threshold_healthy": 25, "threshold_stress": 75}
    },
    "levels": {
        "low": {"max": 20, "color": "#4CAF50"},
        "moderate_low": {"max": 40, "color": "#8BC34A"},
        "moderate": {"max": 60, "color": "#FFEB3B"},
        "high": {"max": 80, "color": "#FF9800"},
        "critical": {"max": 100, "color": "#F44336"}
    }
}
```

---

## Disclaimers

- The risk score is a **data-driven indicator**, not a prediction
- It does NOT account for: crop type, planting date, management practices, irrigation, fertilization
- It does NOT replace professional agronomic assessment
- Weights are based on general agricultural knowledge, not site-specific calibration
- Users should interpret the score alongside field observations
