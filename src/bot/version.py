"""
Bot patch version - single source of truth.

Bump PATCH and add a line to PATCH_NOTES whenever a meaningful change is deployed.
The dashboard reads this via /api/version.
"""

PATCH       = "v1.33"
PATCH_DATE  = "2026-05-11"
PATCH_NOTES = "Brain prompt rewrite #1 of allowed 2 (per BRAIN_RESEARCH_FINDINGS.md). v1.32 produced 95% degraded / 100% non-negative modifier across 48 calls - textbook conservatism bias. New _SYSTEM prompt explicitly: (1) establishes modifier=0.00 as default not as 'neither' fallback, (2) tells the model 'LLMs in trading exhibit conservatism bias - counter this actively', (3) anchors on baseline EV ~-$1/trade so loss clusters are not over-weighted, (4) gives explicit NORMAL reasoning examples (v1 had none), (5) enumerates and forbids the specific anti-patterns v1 produced ('Skip', 'zero edge', 'insufficient conviction', 'soft-exit cluster alone'), (6) tells model edge=0.0 means 'not computed for MR' and to IGNORE it, (7) treats 15m and 4h as equally valid windows. User prompt also cleaned: edge and rv_std fields removed (model misread 0.0 as bearish). STILL ADVISORY-ONLY - brain output continues to be logged but NOT used to alter trade entry. Reset call counter; restart 80-trade observation gate. If this prompt also fails the gate, we have ONE more rewrite per the research rules before killing the brain."
