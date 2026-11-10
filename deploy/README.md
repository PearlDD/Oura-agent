# Oura personal VPS deployment

Prepared for one personal account. JobPilot and other projects are outside this migration.
This directory is a deployment template, not evidence that a server is live.

## Boundary

Caddy is the only published service (80/443); the Python app has no host port.
Caddy issues HTTPS certificates and requires a login on every route, including OAuth.
A separate proxy token also protects the backend. Do not publish port 8765, remove
basic_auth, expose the data volumes, or use multiple app replicas. State is JSON;
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
6. Before migrating data, verify HTTPS, an anonymous 401, a successful authenticated
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

## Daily operation

Scheduling stays disabled during installation (`IRON_SCHEDULE_ENABLED=0`). Enable it only after data, authorization, and restore checks pass and the desktop runner is paused.

Once enabled, the web process checks every 30 seconds. At/after 11:00 America/New_York it attempts
one synchronization/report per date, including same-day catch-up after a restart.
Run state is in private `cloud-runs.json`. Failed/incomplete/crashed attempts do not
retry automatically; use the protected website to synchronize and regenerate manually.
This avoids repeated paid calls after restarts. Missing main sleep or failed sync
blocks scheduled AI; incomplete data is still labelled in the Markdown report.

`IRON_SCHEDULE_AI=0` is the default: synchronization and a data report only. For actual
model decisions, first configure the provider and explicitly authorize daily health
context submission. Then set `IRON_SCHEDULE_AI=1` and
`IRON_SCHEDULE_AI_PROVIDER=gemini` (or `openai`) and recreate the app container.
Changing provider requires updating this opt-in too. Gemini's paid-service confirmation
is also required by the app. No automatic provider fallback occurs. API charges are
separate from VPS charges. A generated AI decision is not a completed workout or an
automatically accepted revision of an existing plan.

Cloud operation updates the protected website and `/reports` volume. It does not
send chat notifications, email, or external messages. Closing the Mac does not stop
the VPS, but a Codex desktop automation cannot itself deliver messages while offline.

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
