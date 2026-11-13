# Oura personal VPS deployment

Prepared for one personal account. JobPilot and other projects are outside this migration.
This directory is a deployment template, not evidence that a server is live.

## Boundary

Caddy is the only published service (80/443); the Python app has no host port.
Caddy issues HTTPS certificates; the app requires a valid session on private routes,
including OAuth, APIs and reports. Only the login page and nonsensitive login/PWA assets
are public. A separate proxy token protects the backend. Do not publish port 8765,
bypass app session checks, expose data volumes, or use multiple app replicas. State is JSON;
only one app process may write it. The report runner therefore lives in that process.
The app runs as UID 10001 with a read-only container filesystem and private data volumes.

## Before starting

1. Confirm the VPS IP, SSH username, and SSH host fingerprint using the OVH console.
   Use SSH keys; keep the private key on your own computer. Never disable host checking.
2. Install Docker Engine and the Compose plugin using Docker's official Ubuntu instructions.
   Verify which Ubuntu release is actually installed before choosing its repository.
3. Point a domain/subdomain A record at the VPS. Only publish an AAAA record if IPv6
   is also configured. Allow SSH and HTTPS/HTTP; preserve SSH access before changing a firewall.
4. Copy this public source to the server. In `deploy`, copy `.env.example` to `.env`
   and set mode 600. Enter the real domain, login username, a bcrypt login hash generated
   by interactive `caddy hash-password`, and a random 32+ character proxy token.
   Keep the bcrypt value single-quoted in `.env` because it contains `$` characters.
   Do not put a plaintext password or API key in the source repository.
5. Run `docker compose config --quiet`, build, and validate the Caddyfile using the
   Caddy image before running `docker compose up -d`. Do not print expanded Compose
   configuration into a shared log: it contains the proxy secret.
6. Before migrating data, verify HTTPS, an anonymous API 401 / page redirect to login, a successful authenticated
   page, and that port 8765 is unreachable from outside.

## Private data and cutover

Keep the original local data as a rollback copy. Make a private snapshot while local
writes are paused. Transfer only over verified SSH to this VPS; never commit/upload it
to GitHub or a static host. Use the private `iron_data` volume with UID/GID 10001 and
mode 700 directories / 600 files. Settings, cached records, feedback, muscle mappings,
preferences, plans and chat history must all survive. Do not replace user preferences
with the application defaults.

Remove all original credentials from the **cloud copy** of settings (training and AI
API keys, Oura client secret, and `oura_tokens`), leaving the local original intact.
Scan the sanitized archive against the source credentials before upload. Reconnect
services in the protected cloud settings page; do not transfer active local tokens. In the Oura developer application, add exactly:

`https://YOUR_DOMAIN/oauth/callback`

Retain the localhost callback for rollback. Sign in to the cloud website and authorize
Oura again there, avoiding two machines rotating the same OAuth refresh token.
Configure Gemini/OpenAI through the protected settings page. Check report dates,
plan versions, feedback and data coverage against the local copy. Export a report and
confirm data survives container recreation. Only then pause the desktop automation.
Do not leave two daily runners active after cutover.

## Sleep-ready operation and phone notifications

Scheduling stays disabled during installation (`IRON_SCHEDULE_ENABLED=0`). After
authorization and verification, set it to 1 and pause the old desktop runner.
The default deployment mode is `IRON_SCHEDULE_MODE=wake`, not a fixed clock time.

The same app process checks Oura every 15 minutes (`IRON_WAKE_POLL_SECONDS=900`).
It waits for today's ended main sleep, today's sleep and readiness scores, and a
stable snapshot for 15 minutes (`IRON_WAKE_STABLE_SECONDS=900`). This is a data
readiness proxy, not real-time detection that the user is awake. Open the Oura App
after waking so the ring can upload. Fragments, future/old sleep end dates, missing
scores and failed polls cannot trigger AI. Poll failures retry at the normal interval
without a model request. A failed model attempt is not automatically repeated after restart. Completed days
continue polling Oura. A changed, stable sleep/recovery snapshot can trigger at most
one automatic revision per day; further changes are marked for explicit review.
A successful manual analysis is reconciled/exported and notified without another
model request. The protected page provides an explicit retry for failed or
incomplete analysis. An already-fresh report from the same model can be reused.

`IRON_SCHEDULE_AI=0` generates data reports only. Actual model decisions require
an explicit provider opt-in: `IRON_SCHEDULE_AI=1` and
`IRON_SCHEDULE_AI_PROVIDER=openai` or `gemini`. The configured provider must match.
Gemini also requires paid-service confirmation. API fees are separate from VPS fees.
A report does not mark a workout complete or accept a plan revision automatically.

Web Push is opt-in per device from the protected website. On iPhone/iPad, add the
site to the Home Screen and open it there before enabling notifications. A user
interaction must request browser permission; the app does not prompt on page load.
Use the test button to confirm receipt. A successful push service response means
accepted for delivery, not proof that the OS displayed it. Focus mode, permissions
and network delivery still matter.

Success and failure notifications have separate per-date deduplication keys. Failure
notices only say that the report is not complete and link to the protected status.
Notifications contain fixed generic text and a report link/date, with no health
metrics, symptoms or training verdict on the lock screen. Standard Web Push routes
the encrypted payload through the browser vendor's push service. Private subscriptions
and `push-vapid.pem` stay in `/data`; protect and back them up with other private data.
The public VAPID key is safe to return to the browser. Unsubscribing stops future
sends to that device; expired endpoints are removed. Automatic delivery attempts
are recorded before sending and deduplicated by date/device. Failed notification
delivery does not erase the report or regenerate it. No email or Telegram is sent.

The service worker handles notification events only. It does not cache private pages,
API responses, credentials or reports for offline use. All app routes, including
subscription settings and the report link, remain protected by the login boundary.
At most one app process may write these JSON state files.

Runtime status is in private `cloud-runs.json`, `wake-poll.json` and
`push-subscriptions.json`, with a summary on the dashboard. The compatibility
`fixed` mode still supports `IRON_SCHEDULE_HOUR`, but the deployed wake mode ignores
that clock threshold.

## Backup and rollback

OVH backup covers the VPS; also retain a separate encrypted private copy under your
control. Before upgrades, stop the app container, snapshot the data and reports volumes
plus private `.env`, and start it again. Caddy certificate volumes should be preserved.
Test restoring into isolated volumes before relying on a backup. Never attach a second
writer to production data. Rollback keeps cloud writes stopped, restores the matching
code/data snapshot, and reauthorizes Oura locally if returning to the Mac.

## Verification status

Unit tests exercise local defaults, cloud host/proxy rejection, consistent OAuth callback,
and daily claim/missing-data/failure behavior. A live domain, TLS, Docker build, SSH and
backup restore must be checked on the actual server before declaring cutover complete.

## Persistent device login

Cloud mode requires `IRON_LOGIN_USER` and `IRON_LOGIN_HASH` (Compose passes the existing
`LOGIN_USER` / `LOGIN_HASH`). Missing or malformed credentials prevent app startup.
The bcrypt dependency is pinned in `requirements-cloud.txt`; local loopback mode
does not require it. Keep the existing password; no provider credentials change.

Remembered sessions last 90 days, or 24 hours server-side for an unremembered browser
session. The `__Host-iron-session` cookie is Secure, HttpOnly, SameSite=Lax and scoped
to `/`. Only SHA-256 token digests, credential tags, broad device categories and
creation/expiry times are persisted in private `/data/login-sessions.json`. This
file is not an API credential or public asset. Device sessions can be revoked from
settings. Changing the username/password hash invalidates old sessions. Protect
backups of this file as private state. Caddy overwrites the client-IP header for
login rate limiting. The app also checks the CSRF nonce and request Origin.

When upgrading from Basic Auth, keep the old Caddy Basic Auth config active while
building/restarting the new app with its required login environment. First verify
that private API routes reject requests without a session, and verify session login
using the old Basic Auth credential plus the new login cookie. Only then replace
and reload Caddy with this template. Rollback must restore Basic Auth before
restoring an old app that has no session checks. Never leave that old app public.

Run `python3 -m unittest -q` after installing cloud requirements for all auth/push
tests; tests requiring optional dependencies skip when those dependencies are absent.
