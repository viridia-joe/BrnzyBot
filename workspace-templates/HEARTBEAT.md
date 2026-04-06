# Heartbeat Checklist

## Daily: TBC Phase Check
Once per day, run: `exec WCL_CLIENT_ID=$WCL_CLIENT_ID WCL_CLIENT_SECRET=$WCL_CLIENT_SECRET bash ~/.openclaw/scripts/check-phase.sh`

If it reports PHASE_CHANGED, read `PHASE.md` and note the change in today's memory file. If PHASE_OK, do nothing.

Track last run in `memory/heartbeat-state.json` under `lastChecks.tbc_phase`.
