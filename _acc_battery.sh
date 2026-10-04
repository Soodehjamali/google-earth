#!/bin/bash
# ACCEPTANCE BATTERY - waits for EE to come up, then fires scenarios sequentially.
# Lives outside backend/ so uvicorn --reload never sees file writes.
BASE=http://127.0.0.1:8001/api/v1/agriculture/analysis
OUT=backend/_acc
mkdir -p $OUT
LOG=$OUT/battery.log
: > $LOG

log() { echo "$(date +%H:%M:%S) $*" >> $LOG; }

POLY='{"type":"Polygon","coordinates":[[[51.80,32.45],[51.842,32.45],[51.842,32.482],[51.80,32.482],[51.80,32.45]]]}'
POINT='{"type":"Point","coordinates":[51.82,32.466]}'

post() { # $1 name, $2 payload
  log "START $1"
  code=$(curl -s -m 420 -o $OUT/$1.json -w "%{http_code}" -X POST $BASE \
    -H "Content-Type: application/json" -d "$2")
  log "END $1 HTTP=$code size=$(wc -c < $OUT/$1.json)"
}

# ---- wait for EE connected (max 45 min) ----
log "waiting for EE"
up=0
for i in $(seq 1 270); do
  resp=$(curl -s -m 45 http://127.0.0.1:8001/api/v1/health/earth-engine 2>/dev/null)
  if echo "$resp" | grep -q '"status":"connected"'; then
    log "EE CONNECTED on try $i"
    up=1
    break
  fi
  sleep 10
done
if [ $up -eq 0 ]; then log "GAVE UP waiting for EE"; exit 1; fi

# ---- fire battery immediately (distinct cloud values bust cache) ----
post s1_fresh "{\"geometry\":$POLY,\"start_date\":\"2024-04-01\",\"end_date\":\"2024-06-30\",\"cloud_max_percent\":25}"
post s2_veg_stress "{\"geometry\":$POLY,\"start_date\":\"2024-03-01\",\"end_date\":\"2024-08-31\",\"domains\":[\"vegetation\"],\"cloud_max_percent\":24}"
post s3_water "{\"geometry\":$POLY,\"start_date\":\"2024-04-01\",\"end_date\":\"2024-06-30\",\"domains\":[\"water\"],\"cloud_max_percent\":23}"
post s4_thermal "{\"geometry\":$POLY,\"start_date\":\"2024-06-01\",\"end_date\":\"2024-08-31\",\"domains\":[\"thermal\",\"climate\"],\"cloud_max_percent\":22}"
post s5_landcrop "{\"geometry\":$POLY,\"start_date\":\"2024-04-01\",\"end_date\":\"2024-06-30\",\"domains\":[\"landcover\",\"crop\"],\"cloud_max_percent\":26}"
post s6_phenology "{\"geometry\":$POLY,\"start_date\":\"2024-01-01\",\"end_date\":\"2024-08-31\",\"domains\":[\"phenology\",\"productivity\"],\"cloud_max_percent\":27}"
post s11_history "{\"geometry\":$POLY,\"start_date\":\"2022-01-01\",\"end_date\":\"2024-12-31\",\"domains\":[\"historical\"],\"cloud_max_percent\":28}"
post s9_short "{\"geometry\":$POINT,\"start_date\":\"2024-05-10\",\"end_date\":\"2024-05-13\",\"domains\":[\"vegetation\"],\"cloud_max_percent\":29}"

# ground truth on top of a separate cache key (fingerprint changes key anyway)
post s8_groundtruth "{\"geometry\":$POLY,\"start_date\":\"2024-04-01\",\"end_date\":\"2024-06-30\",\"cloud_max_percent\":31,\"ground_truth\":[
 {\"observation_id\":\"acc-gt-001\",\"variable\":\"observed_stress\",\"state\":\"present\",\"observed_on\":\"2024-05-15\",\"source\":\"field_observation\",\"method\":\"visual canopy assessment\",\"latitude\":32.466,\"longitude\":51.821},
 {\"observation_id\":\"acc-gt-001\",\"variable\":\"observed_stress\",\"state\":\"present\",\"observed_on\":\"2024-05-15\",\"source\":\"field_observation\",\"method\":\"visual canopy assessment\",\"latitude\":32.466,\"longitude\":51.821},
 {\"observation_id\":\"acc-gt-002\",\"variable\":\"observed_disease\",\"value\":3,\"unit\":\"count\",\"observed_on\":\"2024-05-20\",\"source\":\"agronomist_observation\",\"method\":\"leaflet survey\"}
]}"

log "BATTERY DONE"
