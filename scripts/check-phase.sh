#!/bin/bash
# Check current TBC Anniversary Edition phase by querying Warcraft Logs
# for the highest-tier zone with recent activity on Dreamscythe.
#
# Runs locally via curl + python3. No LLM needed.
# Updates PHASE.md if the phase changed.
#
# Requires: WCL_CLIENT_ID, WCL_CLIENT_SECRET env vars

PHASE_FILE="$HOME/.openclaw/workspace/PHASE.md"
TODAY=$(date +%Y-%m-%d)

# Get WCL token
TOKEN=$(curl -s -X POST "https://www.warcraftlogs.com/oauth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=$WCL_CLIENT_ID&client_secret=$WCL_CLIENT_SECRET" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get WCL token"
  exit 1
fi

# Character config — override with env vars or args
WCL_CHAR_NAME="${WCL_CHAR_NAME:-${1:-Brnz}}"
WCL_SERVER="${WCL_SERVER:-${2:-dreamscythe}}"
WCL_REGION="${WCL_REGION:-us}"

# Check recent reports to see what zones are being raided
RESULT=$(curl -s -X POST "https://classic.warcraftlogs.com/api/v2/client" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"{ characterData { character(name: \\\"$WCL_CHAR_NAME\\\", serverSlug: \\\"$WCL_SERVER\\\", serverRegion: \\\"$WCL_REGION\\\") { recentReports(limit: 10) { data { zone { id name } startTime } } } } }\"}")

# Determine highest phase from zone IDs
# Zone mapping:
#   1007/1048 = T4 (Kara/Gruul/Mag) = Phase 1
#   1008 = T5 (SSC/TK) = Phase 2
#   1010 = T6 (Hyjal/BT) = Phase 3
#   1011 = ZA = Phase 4
#   1012 = Sunwell = Phase 5
#   1009 = Heroic Dungeons (always available)

DETECTED_PHASE=$(echo "$RESULT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
reports = data['data']['characterData']['character']['recentReports']['data']

zone_to_phase = {
    1007: 1, 1048: 1,  # T4
    1008: 2,            # T5
    1010: 3,            # T6
    1011: 4,            # ZA
    1012: 5,            # Sunwell
}

max_phase = 1
for r in reports:
    zid = r['zone']['id']
    phase = zone_to_phase.get(zid, 0)
    if phase > max_phase:
        max_phase = phase

print(max_phase)
" 2>/dev/null)

if [ -z "$DETECTED_PHASE" ] || [ "$DETECTED_PHASE" -eq 0 ]; then
  echo "Could not determine phase from WCL data."
  exit 0
fi

# Phase descriptions
declare -A PHASE_NAMES
PHASE_NAMES[1]="Launch (Karazhan, Gruul, Magtheridon)"
PHASE_NAMES[2]="Overlords of Outland (SSC, Tempest Keep)"
PHASE_NAMES[3]="The Battle for Mount Hyjal (Hyjal, Black Temple)"
PHASE_NAMES[4]="The Gods of Zul'Aman (Zul'Aman)"
PHASE_NAMES[5]="Fury of the Sunwell (Sunwell Plateau)"

PHASE_NAME="${PHASE_NAMES[$DETECTED_PHASE]:-Unknown}"

# Check if phase changed
CURRENT=$(grep "Current Phase:" "$PHASE_FILE" 2>/dev/null | grep -oE "Phase [0-9]")

if [ "Phase $DETECTED_PHASE" != "$CURRENT" ]; then
  echo "Phase changed: $CURRENT -> Phase $DETECTED_PHASE — $PHASE_NAME"
  sed -i "s/\*\*Current Phase:\*\*.*/\*\*Current Phase:\*\* Phase $DETECTED_PHASE — $PHASE_NAME/" "$PHASE_FILE"
  sed -i "s/\*\*Last checked:\*\*.*/\*\*Last checked:\*\* $TODAY/" "$PHASE_FILE"
  echo "PHASE_CHANGED"
else
  sed -i "s/\*\*Last checked:\*\*.*/\*\*Last checked:\*\* $TODAY/" "$PHASE_FILE"
  echo "Phase $DETECTED_PHASE — $PHASE_NAME — no change."
  echo "PHASE_OK"
fi
