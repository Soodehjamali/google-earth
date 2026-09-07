# Limitations & Disclaimers

> This application is a **decision-support system**, not a replacement for field inspection, laboratory analysis, or expert agronomic judgment.

---

## What Satellite Imagery CANNOT Reliably Determine

### Without Additional Ground Data

| Cannot Determine | Why |
|-----------------|-----|
| Exact crop variety / cultivar | Spectral signatures overlap between varieties |
| Confirmed pest infestation | Requires ground-level evidence |
| Confirmed disease diagnosis | Requires laboratory or expert field diagnosis |
| Exact yield prediction | Depends on management, genetics, weather, soil interaction |
| Exact fertilizer requirement | Requires soil testing, crop growth stage, yield targets |
| Exact irrigation requirement | Depends on crop type, root depth, microclimate, soil type |
| Laboratory soil measurements | Remote sensing cannot replace lab analysis |
| Nutrient deficiencies (specific) | Spectral symptoms are non-specific |
| Pollination success | Sub-pixel process, invisible to satellite |

### Resolution Limitations

| Limitation | Impact |
|-----------|--------|
| Sentinel-2: 10m minimum pixel | Cannot resolve features < 10m (rows, individual plants) |
| ERA5: ~9km resolution | Climate data represents large-area averages, not field conditions |
| MODIS: 500m resolution | Land cover classes may mix land uses within a pixel |
| SoilGrids: 250m resolution | Soil properties are modeled estimates, not field measurements |

### Temporal Limitations

| Limitation | Impact |
|-----------|--------|
| 5-day Sentinel-2 revisit (theoretical) | Cloud cover often creates multi-week gaps |
| No real-time data | Satellite passes are scheduled, not on-demand |
| Historical gaps | Pre-2017 Sentinel-2 data uses different sensors |
| Seasonal bias | Analysis quality depends on available cloud-free imagery |

### Atmospheric Limitations

| Limitation | Impact |
|-----------|--------|
| Cloud cover | Blocks surface observation entirely |
| Aerosols/haze | Degrades spectral accuracy |
| Thin cirrus | May not be fully masked |
| Smoke/dust | Temporary spectral distortion |

---

## Data Quality States

Every analysis result includes a quality state:

| State | Criteria |
|-------|----------|
| **good** | Cloud-free imagery available, <10% cloud, >80% spatial coverage, ≤5 day temporal gap |
| **acceptable** | Some cloud cover present, 60-80% spatial coverage, ≤15 day temporal gap |
| **limited** | Significant cloud cover, 40-60% spatial coverage, >15 day temporal gap |
| **insufficient** | <40% spatial coverage, no cloud-free imagery, or missing data |

---

## Uncertainty in Calculated Indices

| Index | Typical Uncertainty | Factors |
|-------|-------------------|---------|
| NDVI | ±0.02–0.05 | Atmosphere, soil background, view angle |
| EVI | ±0.02–0.04 | Blue band noise, atmospheric correction |
| SAVI | ±0.02–0.05 | Soil brightness variability |
| NDWI | ±0.03–0.08 | Atmospheric moisture, surface roughness |

---

## Risk Score Limitations

The agricultural risk score (0–100) is a **composite indicator** based on satellite-derived data:

- It is NOT a prediction of crop failure
- It is NOT a measure of actual economic risk
- It does NOT account for management interventions (irrigation, fertilization)
- It does NOT account for crop variety or planting date
- It is a data-driven indicator that should be interpreted alongside field knowledge

---

## Recommendations

1. **Always cross-reference** with local field observations
2. **Use as a screening tool** to identify areas needing attention
3. **Consult agronomic experts** before making management decisions
4. **Validate with soil tests** for soil-related parameters
5. **Monitor trends** rather than single-point values
6. **Consider weather forecasts** alongside historical climate data

---

## Legal Disclaimer

This application provides informational data derived from satellite imagery and climate reanalysis products. It does not constitute agricultural advice. Users are solely responsible for decisions made based on this information. The developers assume no liability for crop losses, financial damages, or other consequences arising from use of this application.
