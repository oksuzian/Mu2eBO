#!/bin/bash
# List LangGraph checkpoint threads with the wall-clock time of their last
# checkpoint, sorted oldest -> newest. UUIDv6 checkpoint_id is decoded inline.
set -euo pipefail
DB="${1:-/exp/mu2e/app/users/oksuzian/autoresearch/graph_data/checkpoints.sqlite}"

sqlite3 "$DB" \
  "SELECT thread_id, MAX(checkpoint_id) FROM checkpoints GROUP BY thread_id;" \
| python3 -c "
import sys
from datetime import datetime, timezone
OFFSET = int((datetime(1970,1,1,tzinfo=timezone.utc) - datetime(1582,10,15,tzinfo=timezone.utc)).total_seconds()*1e7)
for line in sys.stdin:
    tid, cid = line.strip().split('|')
    h = cid.replace('-','')
    ts = (int(h[0:8],16)<<28) | (int(h[8:12],16)<<12) | (int(h[12:16],16) & 0xfff)
    print(f'{tid:40s}  {datetime.fromtimestamp((ts-OFFSET)/1e7).strftime(\"%Y-%m-%d %H:%M:%S\")}')
" | sort -k2,3
