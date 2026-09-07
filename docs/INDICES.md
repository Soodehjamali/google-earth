# Vegetation Indices — Formulas & Interpretation

> All formulas use verified Sentinel-2 band names from `COPERNICUS/S2_SR_HARMONIZED`.

---

## 1. NDVI — Normalized Difference Vegetation Index

### Formula
```
NDVI = (B8 - B4) / (B8 + B4)
```

### Required Bands
| Band | Name | Central Wavelength |
|------|------|-------------------|
| B8 | NIR | 842 nm |
| B4 | Red | 665 nm |

### Expected Range
| Value | Interpretation |
|-------|---------------|
| -1.0 to 0.0 | Water, snow, clouds |
| 0.0 to 0.1 | Bare soil, rock |
| 0.1 to 0.2 | Sparse vegetation |
| 0.2 to 0.4 | Moderate vegetation |
| 0.4 to 0.6 | Dense vegetation |
| 0.6 to 0.8 | Very dense vegetation |
| 0.8 to 1.0 | Extremely dense vegetation (rare in agriculture) |

### Unit
Dimensionless ratio (−1 to +1)

### Limitations
- Saturates at high biomass levels (>0.8)
- Sensitive to soil background at low vegetation cover
- Affected by atmospheric conditions (clouds, aerosols)
- Does not distinguish between crop types

---

## 2. EVI — Enhanced Vegetation Index

### Formula
```
EVI = G × (B8 - B4) / (B8 + C1 × B4 - C2 × B2 + L)
```

### Coefficients
| Parameter | Value | Description |
|-----------|-------|-------------|
| G | 2.5 | Gain factor |
| C1 | 6 | Red correction coefficient |
| C2 | 7.5 | Blue correction coefficient |
| L | 1 | Canopy background adjustment |

### Required Bands
| Band | Name | Central Wavelength |
|------|------|-------------------|
| B8 | NIR | 842 nm |
| B4 | Red | 665 nm |
| B2 | Blue | 490 nm |

### Expected Range
| Value | Interpretation |
|-------|---------------|
| -1.0 to 0.0 | Water, snow, non-vegetated |
| 0.0 to 0.2 | Sparse vegetation |
| 0.2 to 0.4 | Moderate vegetation |
| 0.4 to 0.6 | Dense vegetation |
| 0.6 to 0.8+ | Very dense vegetation |

### Unit
Dimensionless ratio

### Advantages over NDVI
- Less sensitive to atmospheric effects (uses blue band correction)
- Better performance in high-biomass areas (reduced saturation)
- Improved sensitivity in areas with dense vegetation

### Limitations
- Requires blue band (B2) — available at 10m resolution
- More complex calculation
- Coefficients are empirical and may need adjustment for specific regions

---

## 3. SAVI — Soil-Adjusted Vegetation Index

### Formula
```
SAVI = ((B8 - B4) / (B8 + B4 + L)) × (1 + L)
```

### Parameters
| Parameter | Value | Description |
|-----------|-------|-------------|
| L | 0.5 | Soil brightness correction factor |

### Required Bands
| Band | Name | Central Wavelength |
|------|------|-------------------|
| B8 | NIR | 842 nm |
| B4 | Red | 665 nm |

### Expected Range
| Value | Interpretation |
|-------|---------------|
| -1.0 to 0.0 | Water, snow |
| 0.0 to 0.1 | Bare soil |
| 0.1 to 0.3 | Sparse vegetation |
| 0.3 to 0.5 | Moderate vegetation |
| 0.5 to 0.7 | Dense vegetation |

### Unit
Dimensionless ratio

### Use Cases
- Areas with sparse vegetation where soil background is significant
- Early crop growth stages
- Arid and semi-arid regions
- Post-harvest fields

### Limitations
- Fixed L=0.5 may not be optimal for all soil types
- Less commonly used than NDVI
- Limited comparison literature for some applications

---

## 4. NDWI — Normalized Difference Water Index (McFeeters)

### Formula
```
NDWI = (B3 - B8) / (B3 + B8)
```

### Required Bands
| Band | Name | Central Wavelength |
|------|------|-------------------|
| B3 | Green | 560 nm |
| B8 | NIR | 842 nm |

### Expected Range
| Value | Interpretation |
|-------|---------------|
| -1.0 to 0.0 | Dry/non-water |
| 0.0 to 0.3 | Wet soil, low water content |
| 0.3 to 0.5 | Moderate water content |
| 0.5 to 1.0 | Open water |

### Unit
Dimensionless ratio

### Use Cases
- Surface water detection
- Irrigation monitoring
- Water stress assessment (indirect)
- Wetland mapping

### Limitations
- McFeeters NDWI is better for water detection than vegetation water content
- For vegetation water content, use NDWI (Gao) or NDMI (Normalized Difference Moisture Index)
- Sensitive to atmospheric effects
- Urban areas may produce false positives

---

## 5. NDMI — Normalized Difference Moisture Index (Alternative NDWI)

### Formula
```
NDMI = (B8 - B11) / (B8 + B11)
```

### Required Bands
| Band | Name | Central Wavelength |
|------|------|-------------------|
| B8 | NIR | 842 nm |
| B11 | SWIR 1 | 1610 nm |

### Expected Range
| Value | Interpretation |
|-------|---------------|
| -1.0 to 0.0 | Very low moisture / stressed |
| 0.0 to 0.3 | Low moisture |
| 0.3 to 0.5 | Moderate moisture |
| 0.5 to 0.8 | High moisture / healthy |
| 0.8 to 1.0 | Very high moisture |

### Unit
Dimensionless ratio

### Use Cases
- Vegetation water content estimation
- Drought monitoring
- Crop stress detection
- Irrigation management

### Limitations
- Requires SWIR band (B11, 20m resolution) — resampled for 10m products
- Affected by atmospheric moisture
- Not a direct measurement of soil moisture

---

## Index Comparison

| Index | Bands Used | Best For | Resolution |
|-------|-----------|----------|------------|
| NDVI | B4, B8 | General vegetation health | 10m |
| EVI | B2, B4, B8 | Dense vegetation, atmospheric correction | 10m |
| SAVI | B4, B8 | Sparse vegetation, soil background | 10m |
| NDWI | B3, B8 | Water body detection | 10m |
| NDMI | B8, B11 | Vegetation moisture content | 20m (resampled) |

---

## Data Quality Considerations

All indices should report:
- **Data quality state**: good / acceptable / limited / insufficient
- **Cloud coverage percentage**
- **Number of observations** used in compositing
- **Temporal gap** in observations
- **Spatial coverage** within the geometry
