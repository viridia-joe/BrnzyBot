#!/bin/bash
set -e

# TBC Gear Advisor — One-command setup
# Usage: bash setup.sh
#
# Prerequisites:
#   - Python 3.8+
#   - curl
#   - WCL_CLIENT_ID and WCL_CLIENT_SECRET env vars (or pass interactively)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$SCRIPT_DIR/data"
SCRIPTS_DIR="$SCRIPT_DIR/scripts"
WORKSPACE_DIR="$SCRIPT_DIR/workspace"

echo "=== TBC Gear Advisor Setup ==="
echo ""

# Check prerequisites
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 required"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl required"; exit 1; }

PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python: $PYTHON_VER"

# Check for WCL credentials
if [ -z "$WCL_CLIENT_ID" ] || [ -z "$WCL_CLIENT_SECRET" ]; then
    echo ""
    echo "Warcraft Logs API credentials not found in environment."
    echo "Get them at: https://www.warcraftlogs.com → Settings → Web API → V2 Clients"
    echo ""
    read -p "WCL Client ID: " WCL_CLIENT_ID
    read -p "WCL Client Secret: " WCL_CLIENT_SECRET
    export WCL_CLIENT_ID WCL_CLIENT_SECRET
fi

# Verify WCL credentials
echo ""
echo "Verifying WCL credentials..."
WCL_RESULT=$(curl -s -X POST "https://www.warcraftlogs.com/oauth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials&client_id=$WCL_CLIENT_ID&client_secret=$WCL_CLIENT_SECRET")

if echo "$WCL_RESULT" | python3 -c "import sys,json; json.load(sys.stdin)['access_token']" >/dev/null 2>&1; then
    echo "  WCL auth: OK"
else
    echo "  ERROR: WCL authentication failed. Check your client ID and secret."
    exit 1
fi

# Create directories
echo ""
echo "Creating directories..."
mkdir -p "$DATA_DIR/weights" "$SCRIPTS_DIR"

# Step 1: Download WowSims item data
echo ""
echo "Step 1/4: Downloading WowSims item data..."
curl -sL "https://raw.githubusercontent.com/wowsims/tbc/master/sim/core/items/all_items.go" -o /tmp/all_items.go
echo "  Downloaded $(wc -l < /tmp/all_items.go) lines"

# Step 2: Import into SQLite
echo ""
echo "Step 2/4: Building item database..."
python3 "$SCRIPTS_DIR/import-items.py"

# Step 3: Enrich with Wowhead sources
echo ""
echo "Step 3/4: Enriching with source data..."
echo "  This takes ~15 minutes (scraping Wowhead for 4000+ items)."
echo "  Static loot tables first (instant)..."
python3 "$SCRIPTS_DIR/enrich-boss-drops.py"
python3 "$SCRIPTS_DIR/enrich-tier-tokens.py"
echo ""
echo "  Wowhead enrichment (slow, can Ctrl+C and re-run later — it skips already-enriched items)..."
python3 "$SCRIPTS_DIR/enrich-items.py"

# Step 4: Initial phase detection
echo ""
echo "Step 4/4: Detecting current TBC phase..."
bash "$SCRIPTS_DIR/check-phase.sh"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Item database: $DATA_DIR/tbc_items.db"
echo "Weight files:  $DATA_DIR/weights/"
echo ""
echo "To generate your first gear report:"
echo "  WCL_CLIENT_ID=$WCL_CLIENT_ID WCL_CLIENT_SECRET=$WCL_CLIENT_SECRET \\"
echo "    python3 $SCRIPTS_DIR/compute-upgrades.py --name YOURCHAR --server YOURSERVER --spec destro_warlock"
echo ""
echo "Available specs: $(ls "$DATA_DIR/weights/" | sed 's/.json//g' | tr '\n' ', ' | sed 's/,$//')"
echo ""
echo "Add your WCL credentials to your OpenClaw systemd service:"
echo "  Environment=WCL_CLIENT_ID=$WCL_CLIENT_ID"
echo "  Environment=WCL_CLIENT_SECRET=$WCL_CLIENT_SECRET"
