#!/bin/bash
curl -s -m 120 -X POST http://127.0.0.1:8001/api/v1/agriculture/analysis \
  -H "Content-Type: application/json" \
  -d @_acc_req1.json -o _acc_a2_live_resp.json -w "%{http_code}" > _acc_a2_live_status.txt
