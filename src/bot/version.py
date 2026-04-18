"""
Bot patch version — single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.18"
PATCH_DATE  = "2026-04-18"
PATCH_NOTES = "Migrate to Polymarket CLOB V2 SDK (py-clob-client-v2==1.0.0). Import paths updated: py_clob_client.* → py_clob_client_v2.*. ClobClient constructor and OrderArgs unchanged. Deadline: April 28 cutover."
