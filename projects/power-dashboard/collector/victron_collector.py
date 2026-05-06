# Victron Cerbo GX collector stub for the future solar/battery session.
#
# Planned protocol:
# - Subscribe to Victron MQTT topics under N/{portal_id}/... for solar,
#   battery, grid, and VE.Bus readings.
# - Publish a keep-alive every 60 seconds to R/{portal_id}/keepalive so the
#   Cerbo GX continues publishing local MQTT data.
# - Populate solar_readings and roll solar_export_kwh into energy_totals.
#
# This file is intentionally comment-only for the power-dashboard collector
# session. Do not implement Victron collection here.
