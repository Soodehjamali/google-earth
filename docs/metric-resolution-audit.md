# Metric Resolution & Quality-State Audit (Phase 2)

This document audits all 118 registered metrics in the Agricultural Intelligence Platform, classifying their native resolution and three-state quality category:
- `valid`: Field-scale resolution (<= 30 m) capable of resolving orchard/parcel variation.
- `coarse_context`: Regional context (> 30 m up to 11 km) reflecting regional climate or hydrology.
- `unavailable`: Explicitly unavailable/unsupported metric placeholder returning structured reasons.

**Audit Summary**:
- Total Registered Metrics: 118
- Field-Scale Valid (`valid`): 65
- Regional Coarse Context (`coarse_context`): 49
- Explicitly Unavailable (`unavailable`): 4

| # | Metric Key | Display Name | Domain | Primary Dataset | Native Resolution | Resolution (m) | Quality State |
|---|---|---|---|---|---|---|---|
| 1 | `gdd` | Growing Degree Days | climate | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 2 | `par` | Photosynthetically Active Radiation (proxy) | climate | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 3 | `precipitation` | Precipitation | climate | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 4 | `relative_humidity` | Relative Humidity | climate | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 5 | `solar_radiation` | Solar Radiation | climate | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 6 | `temperature_max` | Maximum Air Temperature | climate | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 7 | `temperature_mean` | Mean Air Temperature | climate | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 8 | `temperature_min` | Minimum Air Temperature | climate | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 9 | `vpd` | Vapour Pressure Deficit | climate | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 10 | `wind_speed` | Wind Speed | climate | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 11 | `climate_trend` | Climate Monthly Trend (ERA5-Land) | history | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 12 | `et_precipitation_deficit` | ET minus Precipitation Water Deficit | irrigation | `MODIS/061/MOD16A2GF` | 500 m | 500 m | **`coarse_context`** |
| 13 | `evapotranspiration_anomaly` | Evapotranspiration Anomaly | irrigation | `MODIS/061/MOD16A2GF` | 500 m | 500 m | **`coarse_context`** |
| 14 | `precipitation_anomaly` | Precipitation Anomaly | irrigation | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 15 | `precipitation_cumulative` | Cumulative Precipitation | irrigation | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 16 | `soil_moisture_rootzone_anomaly` | Root-Zone Soil Moisture Anomaly | irrigation | `NASA/SMAP/SPL4SMGP/008` | 11000 m (9 km EASE-Grid 2.0, delivered on an 11 km pixel) | 11000 m | **`coarse_context`** |
| 17 | `crop_type` | Crop Type Identification (not produced) | landcover | `MODIS/061/MCD12Q1` | 500 m | 500 m | **`coarse_context`** |
| 18 | `land_cover_class` | Land Cover Class Distribution | landcover | `MODIS/061/MCD12Q1` | 500 m | 500 m | **`coarse_context`** |
| 19 | `land_cover_quality` | Land Cover Product Quality Flags | landcover | `MODIS/061/MCD12Q1` | 500 m | 500 m | **`coarse_context`** |
| 20 | `seasonal_evapotranspiration_context` | Seasonal Evapotranspiration Context | productivity | `MODIS/061/MOD16A2GF` | 500 m | 500 m | **`coarse_context`** |
| 21 | `root_zone_soil_moisture_gldas` | Root Zone Soil Moisture (GLDAS-2.1 model, kg/m2) | soil | `NASA/GLDAS/V021/NOAH/G025/T3H` | 27830 m (0.25 degree global grid) | 27830 m | **`coarse_context`** |
| 22 | `soil_available_water_capacity` | Available Water Capacity (0-100 cm root zone) | soil | `ISRIC/SoilGrids250m/v2_0` | 250 m | 250 m | **`coarse_context`** |
| 23 | `soil_field_capacity` | Soil Water Content at 33 kPa (field capacity context) | soil | `ISRIC/SoilGrids250m/v2_0` | 250 m | 250 m | **`coarse_context`** |
| 24 | `soil_moisture_rootzone` | Root Zone Soil Moisture (SMAP L4 assimilated model) | soil | `NASA/SMAP/SPL4SMGP/008` | 11000 m (9 km EASE-Grid 2.0, delivered on an 11 km pixel) | 11000 m | **`coarse_context`** |
| 25 | `soil_moisture_rootzone_era5` | Root Zone Soil Water (ERA5-Land model) | soil | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 26 | `soil_moisture_surface` | Surface Soil Moisture (morning overpass) | soil | `NASA/SMAP/SPL3SMP_E/006` | 9000 m (9 km, EASE-Grid 2.0) | 9000 m | **`coarse_context`** |
| 27 | `soil_moisture_surface_evening` | Surface Soil Moisture (evening overpass) | soil | `NASA/SMAP/SPL3SMP_E/006` | 9000 m (9 km, EASE-Grid 2.0) | 9000 m | **`coarse_context`** |
| 28 | `soil_moisture_wetness` | Root Zone Relative Saturation (SMAP L4 wetness) | soil | `NASA/SMAP/SPL4SMGP/008` | 11000 m (9 km EASE-Grid 2.0, delivered on an 11 km pixel) | 11000 m | **`coarse_context`** |
| 29 | `soil_temperature_0_7cm` | Soil Temperature (0-7 cm) | soil | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 30 | `soil_temperature_7_28cm` | Soil Temperature (7-28 cm) | soil | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 31 | `soil_wilting_point` | Soil Water Content at 1500 kPa (wilting point context) | soil | `ISRIC/SoilGrids250m/v2_0` | 250 m | 250 m | **`coarse_context`** |
| 32 | `evaporative_fraction` | Evaporative Fraction (ET/PET) | stress | `MODIS/061/MOD16A2GF` | 500 m | 500 m | **`coarse_context`** |
| 33 | `lst_day_anomaly` | Daytime Land Surface Temperature Anomaly | stress | `MODIS/061/MOD11A2` | 1000 m | 1000 m | **`coarse_context`** |
| 34 | `lst_day_percentile` | Daytime LST Percentile of Historical Window | stress | `MODIS/061/MOD11A2` | 1000 m | 1000 m | **`coarse_context`** |
| 35 | `plant_available_water_fraction` | Plant Available Water Fraction | stress | `NASA/SMAP/SPL4SMGP/008` | 11000 m (9 km EASE-Grid 2.0, delivered on an 11 km pixel) | 11000 m | **`coarse_context`** |
| 36 | `soil_water_content_ratio` | Soil Water Content / Field Capacity Ratio | stress | `NASA/SMAP/SPL4SMGP/008` | 11000 m (9 km EASE-Grid 2.0, delivered on an 11 km pixel) | 11000 m | **`coarse_context`** |
| 37 | `vpd_anomaly` | Vapour Pressure Deficit Anomaly | stress | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 38 | `vpd_high_duration` | Duration of Above-Reference VPD | stress | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 39 | `land_surface_temperature_day` | Daytime Land Surface Temperature | thermal | `MODIS/061/MOD11A2` | 1000 m | 1000 m | **`coarse_context`** |
| 40 | `land_surface_temperature_mean` | Mean Land Surface Temperature | thermal | `MODIS/061/MOD11A2` | 1000 m | 1000 m | **`coarse_context`** |
| 41 | `land_surface_temperature_night` | Nighttime Land Surface Temperature | thermal | `MODIS/061/MOD11A2` | 1000 m | 1000 m | **`coarse_context`** |
| 42 | `surface_temperature_range` | Day-Night Surface Temperature Range | thermal | `MODIS/061/MOD11A2` | 1000 m | 1000 m | **`coarse_context`** |
| 43 | `fapar` | Fraction of Absorbed PAR | vegetation | `MODIS/061/MCD15A3H` | 500 m | 500 m | **`coarse_context`** |
| 44 | `lai` | Leaf Area Index | vegetation | `MODIS/061/MCD15A3H` | 500 m | 500 m | **`coarse_context`** |
| 45 | `era5_evaporation` | Evaporation (ERA5-Land water balance) | water | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 46 | `era5_potential_evaporation` | Potential Evaporation (ERA5-Land) | water | `ECMWF/ERA5_LAND/DAILY_AGGR` | 11132 m (0.1 degree) | 11132 m | **`coarse_context`** |
| 47 | `evapotranspiration` | Evapotranspiration (actual) | water | `MODIS/061/MOD16A2GF` | 500 m | 500 m | **`coarse_context`** |
| 48 | `evapotranspiration_cumulative` | Cumulative Evapotranspiration | water | `MODIS/061/MOD16A2GF` | 500 m | 500 m | **`coarse_context`** |
| 49 | `potential_evapotranspiration` | Potential Evapotranspiration | water | `MODIS/061/MOD16A2GF` | 500 m | 500 m | **`coarse_context`** |
| 50 | `terrain_historical_trend` | Terrain Historical Trend (not computable) | history | `NASA/NASADEM_HGT/001` | 30 m | 30 m | **`unavailable`** |
| 51 | `crop_biomass_estimate` | Crop Biomass Estimate (not produced) | productivity | — | N/A | — | **`unavailable`** |
| 52 | `crop_yield_estimate` | Crop Yield Estimate (not produced) | productivity | — | N/A | — | **`unavailable`** |
| 53 | `crop_yield_uncertainty` | Yield Estimate Uncertainty (not produced) | productivity | — | N/A | — | **`unavailable`** |
| 54 | `cereal_context` | Winter Cereal Context (2021) | crop | `ESA/WorldCereal/2021/MODELS/v100` | 10 m | 10 m | **`valid`** |
| 55 | `crop_flowering_date` | Flowering Date (not produced) | crop | — | N/A | — | **`valid`** |
| 56 | `crop_harvest_date` | Harvest Date (not produced) | crop | `ESA/WorldCereal/2021/MODELS/v100` | 10 m | 10 m | **`valid`** |
| 57 | `crop_planting_date` | Planting Date (not produced) | crop | `ESA/WorldCereal/2021/MODELS/v100` | 10 m | 10 m | **`valid`** |
| 58 | `maize_context` | Maize Context (2021 main season) | crop | `ESA/WorldCereal/2021/MODELS/v100` | 10 m | 10 m | **`valid`** |
| 59 | `temporary_crop_area` | Temporary Crop Area Estimate (2021) | crop | `ESA/WorldCereal/2021/MODELS/v100` | 10 m | 10 m | **`valid`** |
| 60 | `temporary_crop_context` | Temporary Crop Context (2021) | crop | `ESA/WorldCereal/2021/MODELS/v100` | 10 m | 10 m | **`valid`** |
| 61 | `ndvi_anomaly_absolute` | NDVI Anomaly vs Historical Baseline | history | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 62 | `ndvi_anomaly_persistence` | NDVI Baseline-Deviation Persistence | history | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 63 | `ndvi_anomaly_relative` | NDVI Relative Anomaly | history | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 64 | `ndvi_anomaly_standardized` | NDVI Standardized Anomaly | history | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 65 | `ndvi_change_shift` | NDVI Rolling-Shift Change Detection | history | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 66 | `ndvi_percentile_context` | NDVI Historical Percentile Context | history | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 67 | `ndvi_trend` | NDVI Historical Trend | history | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 68 | `season_timing_history` | Season Timing vs Historical Seasons | history | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 69 | `crop_evapotranspiration` | Crop Evapotranspiration | irrigation | — | N/A | — | **`valid`** |
| 70 | `gross_irrigation_requirement` | Gross Irrigation Requirement | irrigation | — | N/A | — | **`valid`** |
| 71 | `irrigation_water_requirement` | Estimated Irrigation Water Requirement | irrigation | — | N/A | — | **`valid`** |
| 72 | `irrigation` | Irrigation Status (not produced) | landcover | — | N/A | — | **`valid`** |
| 73 | `land_cover_probability` | Dynamic World Class Probabilities | landcover | `GOOGLE/DYNAMICWORLD/V1` | 10 m | 10 m | **`valid`** |
| 74 | `vegetation_activity_peak` | Vegetation Activity Peak | phenology | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 75 | `vegetation_season_amplitude` | Vegetation Seasonal Amplitude | phenology | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 76 | `vegetation_season_end` | Vegetation Season End | phenology | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 77 | `vegetation_season_length` | Vegetation Season Length | phenology | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 78 | `vegetation_season_onset` | Vegetation Season Onset | phenology | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 79 | `vegetation_seasonal_integral` | Vegetation Seasonal Integral (not produced) | phenology | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 80 | `crop_area_normalised_productivity_indicator` | Crop Area-Normalised Productivity Indicator | productivity | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 81 | `seasonal_vegetation_productivity_indicator` | Seasonal Vegetation Productivity Indicator | productivity | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 82 | `soil_bulk_density` | Bulk Density (not produced) | soil | — | N/A | — | **`valid`** |
| 83 | `soil_cation_exchange_capacity` | Cation Exchange Capacity (not produced) | soil | — | N/A | — | **`valid`** |
| 84 | `soil_clay_content` | Clay Content (not produced) | soil | — | N/A | — | **`valid`** |
| 85 | `soil_coarse_fragments` | Coarse Fragments (not produced) | soil | — | N/A | — | **`valid`** |
| 86 | `soil_organic_carbon` | Soil Organic Carbon (not produced) | soil | — | N/A | — | **`valid`** |
| 87 | `soil_ph` | Soil pH (not produced) | soil | — | N/A | — | **`valid`** |
| 88 | `soil_salinity` | Soil Salinity (not produced) | soil | — | N/A | — | **`valid`** |
| 89 | `soil_sand_content` | Sand Content (not produced) | soil | — | N/A | — | **`valid`** |
| 90 | `soil_silt_content` | Silt Content (not produced) | soil | — | N/A | — | **`valid`** |
| 91 | `soil_texture_class` | Soil Texture Class (not produced) | soil | — | N/A | — | **`valid`** |
| 92 | `composite_stress` | Composite Stress Index | stress | — | N/A | — | **`valid`** |
| 93 | `aspect` | Aspect (downslope direction) | terrain | `NASA/NASADEM_HGT/001` | 30 m | 30 m | **`valid`** |
| 94 | `elevation` | Elevation | terrain | `NASA/NASADEM_HGT/001` | 30 m | 30 m | **`valid`** |
| 95 | `slope` | Slope | terrain | `NASA/NASADEM_HGT/001` | 30 m | 30 m | **`valid`** |
| 96 | `terrain_ruggedness` | Terrain ruggedness (elevation standard deviation) | terrain | `NASA/NASADEM_HGT/001` | 30 m | 30 m | **`valid`** |
| 97 | `topographic_wetness_index` | Topographic Wetness Index (not produced) | terrain | — | N/A | — | **`valid`** |
| 98 | `landsat_surface_temperature` | Landsat Surface Temperature | thermal | `LANDSAT/LC08/C02/T1_L2` | 30 m (optical) / 30 m resampled from 100 m (thermal) | 30 m | **`valid`** |
| 99 | `evi` | EVI | vegetation | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 100 | `fcover` | Fraction of Vegetation Cover (not produced) | vegetation | — | N/A | — | **`valid`** |
| 101 | `middle_canopy_dryness_proxy` | Middle-Canopy Dryness Proxy | vegetation | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 102 | `msavi` | MSAVI | vegetation | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 103 | `ndre` | NDRE | vegetation | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 104 | `ndre_anomaly` | NDRE Seasonal Anomaly | vegetation | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 105 | `ndvi` | NDVI | vegetation | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 106 | `rvi` | RVI (dual-pol) | vegetation | `COPERNICUS/S1_GRD` | 10 m (IW GRD) | 10 m | **`valid`** |
| 107 | `savi` | SAVI | vegetation | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 108 | `vh` | VH Backscatter | vegetation | `COPERNICUS/S1_GRD` | 10 m (IW GRD) | 10 m | **`valid`** |
| 109 | `vh_vv` | VH/VV (dB difference) | vegetation | `COPERNICUS/S1_GRD` | 10 m (IW GRD) | 10 m | **`valid`** |
| 110 | `vv` | VV Backscatter | vegetation | `COPERNICUS/S1_GRD` | 10 m (IW GRD) | 10 m | **`valid`** |
| 111 | `cwsi` | Crop Water Stress Index (not produced) | water | — | N/A | — | **`valid`** |
| 112 | `mndwi` | MNDWI (modified water) | water | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 113 | `msi` | MSI (moisture stress) | water | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 114 | `msi_anomaly` | MSI Seasonal Anomaly | water | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 115 | `ndmi` | NDMI (vegetation water) | water | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 116 | `ndmi_anomaly` | NDMI Seasonal Anomaly | water | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 117 | `ndwi` | NDWI (open water) | water | `COPERNICUS/S2_SR_HARMONIZED` | 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10) | 10 m | **`valid`** |
| 118 | `wdi` | Water Deficit Index (not produced) | water | — | N/A | — | **`valid`** |
