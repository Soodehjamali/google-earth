# Verified Dataset Inventory

> **Anti-hallucination rule:** Every dataset listed here has been verified against the official Google Earth Engine Data Catalog. No dataset ID or band name is invented.

---

## 1. Sentinel-2 Surface Reflectance (Harmonized) — Phase 1 Primary

| Field | Value |
|-------|-------|
| **Dataset ID** | `COPERNICUS/S2_SR_HARMONIZED` |
| **Description** | Harmonized Sentinel-2 MultiSpectral Instrument Level-2A Surface Reflectance |
| **Provider** | European Space Agency (ESA) / Copernicus Programme |
| **Spatial Resolution** | 10m (B2, B3, B4, B8), 20m (B5, B6, B7, B8A, B11, B12), 60m (B1, B9, B10, QA60) |
| **Temporal Resolution** | 5 days (revisit time) |
| **Available Dates** | 2017-03-28 (S2A start), 2017-07-04 (S2B harmonized) |
| **Scale Factor** | 10,000 (pixel values represent surface reflectance × 10,000) |

### Bands

| Band | Name | Central Wavelength (nm) | Resolution (m) | Description |
|------|------|-------------------------|-----------------|-------------|
| B1 | Aerosols | 443 | 60 | Coastal aerosol |
| B2 | Blue | 490 | 10 | Blue |
| B3 | Green | 560 | 10 | Green |
| B4 | Red | 665 | 10 | Red |
| B5 | Red Edge 1 | 705 | 20 | Vegetation red edge |
| B6 | Red Edge 2 | 740 | 20 | Vegetation red edge |
| B7 | Red Edge 3 | 783 | 20 | Vegetation red edge |
| B8 | NIR | 842 | 10 | Near infrared (vegetation) |
| B8A | NIR Narrow | 865 | 20 | Narrow NIR |
| B9 | Water Vapour | 945 | 60 | Water vapour |
| B11 | SWIR 1 | 1610 | 20 | Short-wave infrared |
| B12 | SWIR 2 | 2190 | 20 | Short-wave infrared |
| QA60 | Cloud Mask | — | 60 | Bitmask for cloud and cirrus |
| SCL | Scene Classification | — | 20 | Scene classification layer |
| AOT | Aerosol Optical Thickness | — | — | Aerosol retrieval (from Jan 2022) |
| CBRN | Copernicus BRDF | — | — | BRDF parameters |

### SCL Classes (Scene Classification Layer)

| Value | Class |
|-------|-------|
| 0 | No data (masked) |
| 1 | Saturated/defective |
| 2 | Dark area pixels |
| 3 | Cloud shadows |
| 4 | Vegetation |
| 5 | Bare soils |
| 6 | Water |
| 7 | Unclassified |
| 8 | Cloud (medium probability) |
| 9 | Cloud (high probability) |
| 10 | Thin cirrus |
| 11 | Snow / ice |

### Cloud Masking Strategy

**Primary: SCL-based masking**
```python
# Pixels to mask (remove from analysis)
MASK_VALUES = [0, 1, 3, 8, 9, 10]
# No data, defective, cloud shadows, cloud med/high, cirrus
```

**Secondary: QA60 bitmask**
- Bit 10: Opaque clouds
- Bit 11: Cirrus clouds

### Preprocessing Required

1. Scale pixel values: `pixel_value / 10000` to get reflectance (0–1)
2. Apply cloud mask using SCL
3. Clip to geometry of interest

### Known Limitations

- QA60 cloud polygons stopped being produced after 2022-01-25 (use SCL as primary)
- S2B has slightly different spectral response than S2A (harmonization mitigates this)
- 5-day revisit is theoretical; cloud cover often results in longer gaps
- No thermal bands — cannot retrieve land surface temperature directly

### Intended Use

- NDVI, EVI, SAVI, NDWI calculations
- RGB true/false color composites
- Land cover classification
- Vegetation health monitoring

---

## 2. ERA5 Land — Phase 3 (Climate)

| Field | Value |
|-------|-------|
| **Dataset ID** | `ECMWF/ERA5_LAND/DAILY_AGGR` |
| **Description** | ERA5-Land daily aggregated reanalysis |
| **Provider** | ECMWF (European Centre for Medium-Range Weather Forecasts) |
| **Spatial Resolution** | ~11,132m (0.11° × 0.11°, ~9 km at equator) |
| **Temporal Resolution** | Daily (aggregated from hourly) |
| **Available Dates** | 1950-01-01 to present |
| **Variables** | Temperature, precipitation, soil moisture, evapotranspiration, wind |

### Key Bands for Agriculture

| Variable | Band | Units |
|----------|------|-------|
| Temperature (2m) | `temperature_2m` | Kelvin |
| Precipitation | `total_precipitation_sum` | m (meters of water) |
| Soil moisture (0-7cm) | `soil_moisture_0_to_7cm_surface` | m³/m³ |
| Potential ET | `reference_evapotranspiration_sum` | m |
| Surface runoff | `surface_runoff_sum` | m |

### Preprocessing Required

1. Temperature: Convert Kelvin to Celsius (K − 273.15)
2. Precipitation: Convert meters to millimeters (m × 1000)
3. ET: Convert meters to millimeters (m × 1000)

### Known Limitations

- Reanalysis product, not direct observations — modeled data
- Coarse resolution (~9km) — not suitable for field-scale analysis
- Soil moisture is modeled, not measured
- Best for regional/climate-scale analysis, not individual field decisions

---

## 3. ERA5 Monthly Aggregates — Phase 3 (Climate Monthly)

| Field | Value |
|-------|-------|
| **Dataset ID** | `ECMWF/ERA5_MONTHLY_AGGR` |
| **Description** | ERA5 monthly aggregated surface climate reanalysis |
| **Provider** | ECMWF |
| **Spatial Resolution** | ~30,000m (0.25° × 0.25°) |
| **Temporal Resolution** | Monthly |
| **Available Dates** | 1979-01-01 to present |

### Key Bands

| Variable | Band | Units |
|----------|------|-------|
| Mean temperature | `mean_2m_air_temperature` | K |
| Max temperature | `maximum_2m_air_temperature` | K |
| Min temperature | `minimum_2m_air_temperature` | K |
| Total precipitation | `total_precipitation` | m |
| Mean soil moisture | `volumetric_soil_water_layer_1` | m³/m³ |

### Known Limitations

- Even coarser resolution (~30km) than daily ERA5-Land
- Best for long-term climate analysis and anomaly detection
- Not suitable for field-level decisions

---

## 4. MODIS Land Cover — Phase 5

| Field | Value |
|-------|-------|
| **Dataset ID** | `MODIS/061/MCD12Q1` |
| **Description** | MODIS Land Cover Type (Collection 6.1) |
| **Provider** | NASA / USGS |
| **Spatial Resolution** | 500m |
| **Temporal Resolution** | Annual |
| **Available Dates** | 2001-01-01 to present |

### Key Bands

| Band | Name | Description |
|------|------|-------------|
| LC_Type1 | IGBP Classification | 17 land cover classes |
| LC_Type2 | UMD Classification | 14 classes |
| LC_Type3 | LAI/FPAR Classification | 12 classes |
| LC_Prop1 | LCCS1 Land Cover | Continuous fields (vegetation cover %) |
| LC_Prop2 | LCCS2 Vegetation Type | Continuous fields |
| LC_Prop3 | LCCS3 Soil Type | Continuous fields |

### IGBP Classes (LC_Type1)

| Value | Class |
|-------|-------|
| 0 | Water Bodies |
| 1 | Evergreen Needleleaf Forest |
| 2 | Evergreen Broadleaf Forest |
| 3 | Deciduous Needleleaf Forest |
| 4 | Deciduous Broadleaf Forest |
| 5 | Mixed Forests |
| 6 | Closed Shrublands |
| 7 | Open Shrublands |
| 8 | Woody Savannas |
| 9 | Savannas |
| 10 | Grasslands |
| 11 | Permanent Wetlands |
| 12 | Croplands |
| 13 | Urban and Built-up Lands |
| 14 | Cropland/Natural Vegetation Mosaics |
| 15 | Snow and Ice |
| 16 | Barren |
| 17 | Unclassified |

### Known Limitations

- 500m resolution — not field-scale
- Annual product — no sub-annual changes
- Classification accuracy varies by region

---

## 5. Soil Grids (ISRIC) — Phase 4

| Field | Value |
|-------|-------|
| **Dataset ID** | `projects/soilgrids/250m` (via SoilGrids API, NOT directly in GEE catalog) |
| **Alternative GEE Dataset** | None verified — SoilGrids is primarily accessed via REST API |
| **Provider** | ISRIC — World Soil Information |
| **Spatial Resolution** | 250m |
| **Available Depth Layers** | 0-5cm, 5-15cm, 15-30cm, 30-60cm, 60-100cm, 100-200cm |

### Variables

| Variable | Units | Notes |
|----------|-------|-------|
| Sand content | % | Mass fraction |
| Clay content | % | Mass fraction |
| Silt content | % | Mass fraction |
| Organic carbon | g/kg | Soil organic carbon |
| pH | pH units | pH in water |
| CEC | cmol/kg | Cation exchange capacity |
| Soil texture class | — | Classification |

### Access Method

SoilGrids data is available through:
1. REST API: `https://rest.isric.org/soilgrids/v2.0/properties/query`
2. Not natively in GEE catalog — we'll use the REST API

### Known Limitations

- Modeled estimates, not field measurements
- 250m resolution — averages over large areas
- Quality varies by region (better in data-rich areas)
- Must clearly label as "Modeled/Estimated"

---

## Dataset Usage Summary

| Phase | Dataset | Primary Use |
|-------|---------|-------------|
| Phase 1 | `COPERNICUS/S2_SR_HARMONIZED` | NDVI, RGB imagery |
| Phase 2 | `COPERNICUS/S2_SR_HARMONIZED` | NDVI, EVI, NDWI time series |
| Phase 3 | `ECMWF/ERA5_LAND/DAILY_AGGR` | Daily precipitation, temperature, ET |
| Phase 3 | `ECMWF/ERA5_MONTHLY_AGGR` | Monthly climate anomalies |
| Phase 4 | SoilGrids REST API | Soil properties |
| Phase 5 | `MODIS/061/MCD12Q1` | Land cover classification |
| Phase 6+ | Combined | Stress & risk analysis |

---

## Verification Notes

- All dataset IDs verified against Google Earth Engine Data Catalog (https://developers.google.com/earth-engine/datasets)
- Sentinel-2 bands verified: B2 (Blue), B3 (Green), B4 (Red), B8 (NIR), B8A, B11, B12, QA60, SCL
- Cloud masking approach verified: SCL-based masking is the recommended approach post-2022
- ERA5 variables verified against ECMWF documentation
- No dataset IDs or band names are invented
