# فاز ۳ - موجودی عوامل تحلیلی سرمازدگی پلتفرم (Platform Factor Inventory)
تاریخ استخراج: ۲۰۲۶-۱۰-۱۸
شاخه: `phase-3-frost`

این سند موجودی کامل تمامی عوامل مورد استفاده در مدل وزنی بازطراحی‌شده سرمازدگی (R3) را مشخص می‌کند. مطابق اصل اساسی طراحی (P1)، مقادیر عواملی که پلتفرم پیش‌تر آن‌ها را محاسبه می‌کند مستقیماً از داده‌های تحلیلی موجود پلتفرم به ازای هر باغ استخراج می‌شوند و از ایجاد مسیر موازی داده (Parallel Data Path) اکیداً پرهیز می‌شود. تنها مواردی که پلتفرم فاقد پیش‌بینی آن‌ها است (باد، ابر و رطوبت پیش‌بینی آینده) از خروجی‌های NOAA/GFS استخراج می‌گردند.

---

## ۱. خروجی خام جستجوها و بازرسی‌های کد (Raw Grep & Code Output)

### ۱.۱. ثبت مجموعه‌داده‌های پلتفرم در `app.services.agriculture.registry.REGISTRY`
```text
COPERNICUS/S2_SR_HARMONIZED ('primary',) 10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10)
LANDSAT/LC08/C02/T1_L2 ('primary',) 30 m (optical) / 30 m resampled from 100 m (thermal)
LANDSAT/LC09/C02/T1_L2 ('primary',) 30 m (optical) / 30 m resampled from 100 m (thermal)
COPERNICUS/S1_GRD ('primary',) 10 m (IW GRD)
MODIS/061/MCD15A3H ('primary',) 500 m
MODIS/061/MCD12Q1 ('primary',) 500 m
GOOGLE/DYNAMICWORLD/V1 ('primary',) 10 m
ESA/WorldCereal/2021/MODELS/v100 ('primary',) 10 m
ECMWF/ERA5_LAND/DAILY_AGGR ('primary',) 11132 m (0.1 degree)
IDAHO_EPSCOR/TERRACLIMATE ('primary',) 4638.3 m (1/24 degree)
MODIS/061/MOD16A2GF ('primary',) 500 m
MODIS/061/MOD16A2 ('fallback', 'recent') 500 m
MODIS/061/MOD11A2 ('primary',) 1000 m
MODIS/061/MOD11A1 ('fallback', 'daily') 1000 m
NASA/SMAP/SPL3SMP_E/006 ('primary',) 9000 m (9 km, EASE-Grid 2.0)
NASA/SMAP/SPL3SMP_E/005 ('fallback', 'historical') 9000 m (9 km, EASE-Grid 2.0)
NASA/SMAP/SPL4SMGP/008 ('assimilated_model',) 11000 m (9 km EASE-Grid 2.0, delivered on an 11 km pixel)
NASA/GLDAS/V021/NOAH/G025/T3H ('modelled_root_zone',) 27830 m (0.25 degree global grid)
ISRIC/SoilGrids250m/v2_0 ('static_soil_property',) 250 m
NASA/NASADEM_HGT/001 ('primary',) 30 m
USGS/SRTMGL1_003 ('fallback',) 30 m
```

### ۱.۲. خروجی بررسی متریک‌های رطوبت ریشه در خاک (`app.services.agriculture.soil`)
```text
soil_moisture_rootzone domain=soil unit=m3/m3 dataset_ids=('NASA/SMAP/SPL4SMGP/008',)
soil_moisture_rootzone_era5 domain=soil unit=m3/m3 dataset_ids=('ECMWF/ERA5_LAND/DAILY_AGGR',)
root_zone_soil_moisture_gldas domain=soil unit=kg/m2 dataset_ids=('NASA/GLDAS/V021/NOAH/G025/T3H',)
```

### ۱.۳. خروجی بررسی ظرفیت مزرعه، نقطه پژمردگی و مشخصات خاک (`soil_properties.py` و `soil_intelligence.py`)
```text
soil_available_water_capacity domain=soil unit=cm3/cm3 dataset_ids=('ISRIC/SoilGrids250m/v2_0',)
soil_field_capacity domain=soil unit=cm3/cm3 dataset_ids=('ISRIC/SoilGrids250m/v2_0',)
soil_wilting_point domain=soil unit=cm3/cm3 dataset_ids=('ISRIC/SoilGrids250m/v2_0',)
compute_soil_intelligence(geometry):
  - water_retention: field_capacity_33kpa (wv0033), wilting_point_1500kpa (wv1500), available_water_capacity
  - texture_classification: class_en, class_fa (via classify_usda_texture on sand/silt/clay 0-100cm)
  - sand/silt/clay root_zone_value (0-100cm profile mean)
```

### ۱.۴. خروجی بررسی متریک‌های توپوگرافی و تراز ارتفاع (`app.services.agriculture.terrain` و `cold_air_pooling.py`)
```text
elevation domain=terrain unit=m dataset_ids=('NASA/NASADEM_HGT/001', 'USGS/SRTMGL1_003')
slope domain=terrain unit=degrees dataset_ids=('NASA/NASADEM_HGT/001', 'USGS/SRTMGL1_003')
aspect domain=terrain unit=degrees dataset_ids=('NASA/NASADEM_HGT/001', 'USGS/SRTMGL1_003')
terrain_ruggedness domain=terrain unit=m dataset_ids=('NASA/NASADEM_HGT/001', 'USGS/SRTMGL1_003')
compute_cold_air_pooling_proxy(geometry): returns pooling_risk_proxy in [0, 1] using NASADEM 30m
```

### ۱.۵. خروجی بررسی شرایط اقلیمی، باد و فنولوژی پلتفرم
```text
relative_humidity domain=climate unit=percent dataset_ids=('ECMWF/ERA5_LAND/DAILY_AGGR',) [بازتحلیل گذشته‌نگر با تاخیر ۵ روزه - پیش‌بینی نیست]
wind_speed domain=climate unit=m/s dataset_ids=('ECMWF/ERA5_LAND/DAILY_AGGR',) [بازتحلیل گذشته‌نگر با تاخیر ۵ روزه - پیش‌بینی نیست]
vegetation_season_onset domain=phenology unit=decimal_year (SOS Sentinel-2 10m / MODIS)
```

---

## ۲. جدول موجودی عوامل مدل سرمازدگی (Factor Inventory Table)

| ردیف عامل | عنوان فارسی / انگلیسی | منبع پلتفرم یا وضعیت GFS | ماژول و تابع تامین‌کننده | شناسه متریک / دیتاست | تفکیک مکانی (Resolution) | وضعیت کیفیت داده | تازگی داده (Cadence / Latency) | یکای سنجش |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **دما و دیرش** | کمینه دمای تصحیح‌شده و دیرش زیر آستانه | موجود در پلتفرم (پیش‌بینی GFS + اصلاح DEM) | `app.services.agriculture.forecast` / `frost_risk` | `NOAA/GFS0P25` + `NASADEM 30m` | ~۲۸ کیلومتر با تصحیح ارتفاعی ۳۰ متری | `valid` (ارتفاع) / `coarse_context` (هواشناسی) | ساعتی، پیش‌بینی زنده تا ۲۴۰ ساعت | درجه سانتی‌گراد (°C) و ساعت (h) |
| **مرحله فنولوژی** | مرحله فنولوژیکی باغ | موجود در پلتفرم (رکورد باغدار + راهنمای پلتفرم) | دیتابیس `Orchard.current_stage` + `phenology.py` | `vegetation_season_onset` | ۱۰ متری (سنتینل-۲) / ورود باغدار | `valid` (ورود باغدار) | به‌روزشده توسط باغدار | کلید مرحله |
| **رطوبت ناحیه ریشه** | رطوبت ریشه (۰ تا ۱۰۰ سانتیمتر) | موجود در پلتفرم | `app.services.agriculture.soil` / `soil_intelligence` | `soil_moisture_rootzone` (`NASA/SMAP/SPL4SMGP/008`) یا `ERA5-Land` | ۱۱ کیلومتر | `coarse_context` (یا `valid` در صورت ورود باغدار) | روزانه (تاخیر ۲ الی ۳ روزه) | $m^3/m^3$ |
| **ظرفیت مزرعه و پژمردگی** | حد ظرفیت مزرعه و نقطه پژمردگی دائم | موجود در پلتفرم | `app.services.agriculture.soil_intelligence` / `soil_properties` | `ISRIC/SoilGrids250m/v2_0` (wv0033 / wv1500) | ۲۵۰ متر | `valid` (نقشه مبنای خاک) | ایستا (Static Baseline) | $cm^3/cm^3$ یا $m^3/m^3$ |
| **بافت و عمق خاک** | رده بافت خاک و درصد شن/رس/سیلت | موجود در پلتفرم | `app.services.agriculture.soil_intelligence.compute_soil_intelligence` | `ISRIC/SoilGrids250m/v2_0` | ۲۵۰ متر | `valid` / `coarse_context` | ایستا (Static Baseline) | درصد و رده بافت USDA |
| **سرعت باد** | سرعت باد سطحی ۱۰ متری | **در پلتفرم موجود نیست: استخراج از GFS** | `NOAA/GFS0P25` | `u_component_of_wind_10m_above_ground`, `v_component...` | ~۲۸ کیلومتر | `coarse_context` | پیش‌بینی زنده ساعتی | متر بر ثانیه ($m/s$) |
| **جهت باد** | جهت وزش باد در ساعت کمینه دما | **در پلتفرم موجود نیست: استخراج از GFS** | رابطه جهت هواشناسی از $u, v$ در GFS | استخراج برداری از GFS | ~۲۸ کیلومتر | `coarse_context` | پیش‌بینی زنده ساعتی | درجه جغرافیایی ($0-360^\circ$) |
| **پوشش ابر** | درصد کل پوشش ابر آسمان | **در پلتفرم موجود نیست: استخراج از GFS** | `NOAA/GFS0P25` | `total_cloud_cover_entire_atmosphere` | ~۲۸ کیلومتر | `coarse_context` | پیش‌بینی زنده ساعتی | درصد (%) |
| **رطوبت نسبی / نقطه شبنم** | رطوبت نسبی هوا و دمای نقطه شبنم | **در پلتفرم موجود نیست: استخراج از GFS** | `NOAA/GFS0P25` + فرمول مگنوس | `relative_humidity_2m_above_ground` | ~۲۸ کیلومتر | `coarse_context` | پیش‌بینی زنده ساعتی | درصد (%) و دمای شبنم (°C) |
| **شاخص تجمیع سرما** | ضریب فرورفتگی و استخر هوای سرد | موجود در پلتفرم | `app.services.agriculture.cold_air_pooling` | `compute_cold_air_pooling_proxy` (`NASADEM 30m`) | ۳۰ متر | `valid` | ایستا (مدل رقومی ارتفاع) | شاخص بین ۰ و ۱ |
| **شیب و جهت دامنه** | شیب زمین و جهت جغرافیایی شیب | موجود در پلتفرم | `app.services.agriculture.terrain` | `slope`, `aspect` (`NASADEM 30m`) | ۳۰ متر | `valid` | ایستا (مدل رقومی ارتفاع) | درجه ($^\circ$) |

---

## ۳. حذف و جایگزینی مسیرهای داده موازی (Elimination of Parallel Paths)
در تغییرات قبلی E9، عواملی نظیر رطوبت خاک و بافت خاک به صورت متغیرهای درون‌خطی فرضی یا مستقل ارزیابی می‌شدند. در طراحی جدید (R1-R3):
1. **یک منبع واحد برای خاک:** مقادیر بافت خاک، درصد شن، ظرفیت مزرعه ($FC$) و نقطه پژمردگی ($WP$) منحصراً از خروجی تابع معتبر `compute_soil_intelligence(geometry)` پلتفرم خوانده می‌شوند.
2. **یک منبع واحد برای توپوگرافی:** ارتفاع سایت، شیب، جهت شیب و شاخص تجمیع هوای سرد منحصراً از ماژول‌های `app.services.agriculture.terrain` و `app.services.agriculture.cold_air_pooling` استخراج می‌گردند.
3. **شفافیت پیرامون داده‌های جوی:** مشخص گردید که پلتفرم فاقد سرویس پیش‌بینی وضع هوا برای باد و ابر در آینده است و تنها داده‌های گذشته‌نگر بازتحلیل ERA5-Land را دارد؛ از این رو سرعت باد، جهت باد، ابر، رطوبت نسبی و نقطه شبنم آینده منحصراً از خروجی زنده GFS استخراج می‌گردند و برچسب عدم وجود در پلتفرم را همراه دارند.
