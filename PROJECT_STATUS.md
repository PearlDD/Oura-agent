# Current project status

Technical handoff checkpoint: 2026-11-18 (America/New_York).
Read this file and README.md when continuing in a new chat. Fetch origin/main and
compare the checkout before editing; a new chat may start from a different folder
or an older checkout. Conversation history is not a substitute for repository state.

## Current implementation

- User preference: automatic refresh follows the ended main NIGHT sleep only.
  Main-sleep duration/times/HRV/heart rate/breathing/efficiency corrections can trigger
  a stable new revision. Steps, naps and changes to today's daily sleep/readiness
  scores, contributors or daily temperature aggregates do not invalidate the morning
  snapshot or trigger generation. Those aggregates remain available as input snapshots.
  Actual training/plan/feedback changes still require checking advice but do not trigger
  automatic daytime generation; manual analysis remains available. Fingerprint v3
  migrates a previous-policy decision only with a verified original context; a fresh
  verified report registers sleep identity v2 without another model call. Failed or
  reverted night versions remain deduplicated. Do not restore the prior broad
  full-context automatic refresh: this narrower policy is explicitly user requested.

- The homepage load chart shows all catalogued muscle groups, including chest,
  front delts and serratus, independent of planning priorities. Support/control
  involvement is shown separately and does not inflate strength bars. Zero display
  rows for inactive groups are presentation-only; model rows, fingerprints and
  allocations remain unchanged. Coverage caveats still apply to all bars.

- Missing optional Symptom Radar/RPE/cycle fields do not themselves require a
  clarify verdict or repetitive user entry. Unknown Strain is omitted from key
  clues; an explicit dated user report of no signs is shown with its source.
  Pending training matching does not automatically shift the calendar or block
  a planned rest day; until the user confirms a shift, evaluate the saved schedule.

- AI generation transport waits up to 180 seconds; ordinary data requests retain
  60 seconds. Timeout/connection failures save only sanitized categories and elapsed
  time, never raw exceptions or secrets. Ambiguous failed generations are not blindly
  rebilled: the existing explicit scheduler retry remains the recovery action.

- Plan UI uses a selectable week strip and a full-width day table (`static/plans.js`).
  Imported original prescriptions are returned separately as `coach_agent.plan_baselines`.
  The table distinguishes original/current arrangements and pending revisions, highlights
  changed rows, and keeps preparation and historical weights collapsed. Unknown RIR and
  qualitative distances stay unknown; no chat prose is converted into a saved revision.
  A proposal needs the existing explicit acceptance action. Chat bold text is rendered
  with safe text nodes. UI-only changes require no new model call.

- Personal VPS deployment uses Docker Compose and Caddy HTTPS. Localhost instructions
  are for local development only. Production data/settings live in private volumes.
- Cloud login has revocable remembered-device sessions. Login state survives app
  recreation; credentials and provider tokens are not part of this repository.
- The cloud runner checks Oura every 15 minutes and waits for a stable, ended main
  sleep with sleep/readiness data. This is data readiness, not detection of actual waking.
- Each distinct stable sleep/recovery snapshot can update the analysis. Previously
  processed snapshots are deduplicated; a failed identical snapshot is not rebilled
  automatically. Successful manual analyses can be reconciled without another model call.
- Today's rolling activity counters do not alone expire a morning analysis. Real
  sleep/recovery/training/plan/feedback changes still invalidate its basis.
- Old-page CSRF rejection refreshes the token and retries once, before any action
  was executed. Network errors, 5xx and origin failures are not automatically retried.
- Planned rest is neutral; red is for replacing planned training with rest.
- Web Push initialization is independent of homepage loading order and timezone state.
  It supports explicit rechecking, foreground checks and safe failure-stage messages.
  Initialization does not prompt for permission or delete/recreate subscriptions.
- Push-service acceptance does not prove that the phone displayed a notification.
  End-to-end confirmation requires observing the phone, not just HTTP success.

## Relevant fixes already on main

- `72fb707`: notification initialization race and device recheck recovery.
- `552d811`: planned-rest colors and Agent draft provenance.
- `94290af`: stale CSRF recovery.
- `3fe7c06`: rolling activity no longer falsely expires analysis.
- `9aec4b2`: revisions for distinct stable sleep snapshots.

## Imported-program support and remaining limitation

The website supports user-confirmed private program import: exact set rows, cyclic
training/rest dates, historical load references and explicit whole-cycle shifts.
A confirmed unfinished day shifts subsequent training AND rest; missing records
are not enough to trigger shifts. Source activation archives unfinished web plans;
completed/skipped records remain. Unknown RIR/dose remains unknown; qualitative distances can be retained without inventing metres or seconds. Overdue unverified training is surfaced for follow-up, not automatically marked missed. Imported plans
currently permit textual AI changes or separately confirmed rest proposals; direct
AI exercise-row replacement is blocked to preserve variable sets and unknown dose.
Without an import, plans remain Agent drafts. Imported programs are not a live
mirror of SynFit or its auto-postponed calendar. Training logs, official plans and personal templates are different sources.
The documented personal-template interface is restricted to the dedicated Agent
folder; do not claim access to arbitrary user folders. Align the real source plan
before claiming a recommendation evaluates that existing plan. An absent API result
is not proof the user has no plan.

## Verification and continuation

The cloud image passed 106 Python tests after the imported-program change. Browser regressions are
covered by synthetic tests that do not use credentials, health data or network:

```sh
python3 -m unittest -q
node test_api.js
node test_decision_ui.js
node test_push_ui.js
node test_program_ui.js
node test_plans_ui.js
```

Install requirements-cloud.txt in an isolated environment to run dependency-specific
Python tests; otherwise some tests skip. Preserve private settings, feedback, plans,
VAPID keys, subscriptions and data volumes during deployment. Do not overwrite them
with defaults, run a second writer or publish them. Keep the old desktop scheduler
paused unless a deliberate migration back is requested. No model call is needed
just to verify an interface or notification fix.
