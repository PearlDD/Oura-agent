# Oura-agent / Pearl's Health Tracker

AI agent for Pearl's Oura ring: a local, personal lifting and recovery journal combining Xunji workout records with Oura sleep and recovery data.

## Public website

- About: https://pearldd.github.io/Oura-agent/
- Privacy Policy: https://pearldd.github.io/Oura-agent/privacy.html
- Terms of Service: https://pearldd.github.io/Oura-agent/terms.html

The public site contains product information and policies only. It does not run the private dashboard or store personal health data.

## Run locally

Python 3.10+; no third-party dependencies required. Double-click `启动.command` on macOS, or run:

```sh
python3 launch.py
```

Open http://127.0.0.1:8765 . Keep the local server running while using the dashboard. Connect your own accounts under **连接与设置**.

## Oura registration

Create an OAuth application in the Oura developer portal. Use the public website and policy URLs above. Register this exact local redirect URI:

```text
http://localhost:8765/oauth/callback
```

Enter your Client ID and Client Secret into the local dashboard, then authorize Oura. The MVP requests the `daily` scope. Oura account/membership requirements apply. GitHub Pages is not the OAuth callback server; the local Python app handles the callback.

## Features

- Read-only Xunji v2 sync, 7 or 28 days; no source-account writes.
- Completed working sets, kg/lb normalization, recorded RPE, supersets and drop sets.
- Same-exercise comparisons, daily journal and Markdown export.
- Oura OAuth with PKCE/state, refresh-token rotation and pagination.
- Recovery baselines from up to 28 prior days, requiring at least 7 valid nights.
- Optional OpenAI Responses API interpretation; configure your own key/model, opt in and generate manually. Basic reports do not require AI.

## Private runtime data

Runtime files are stored outside this source folder by default, in `work/iron-oura-data/` two levels above it. Set `IRON_DATA_DIR` to override. They contain health records and secrets; do not publish them. Files have restricted filesystem permissions but are not encrypted by the app. Deleting local tokens does not revoke provider access; use provider account controls.

Default timezone: `America/New_York` (`IRON_TIMEZONE` override). Default port: `8765` (`IRON_PORT` override; update your Oura redirect URI accordingly). The server binds only to 127.0.0.1. This is a single-user local prototype, not a production multi-user service. No unattended scheduler is configured.

## Tests

```sh
python3 -m unittest -v
node --check static/app.js
```

Tests use temporary directories and mocked provider responses. Real Oura authorization and real OpenAI generation require your own configuration. No credentials, personal workout logs or private runtime data are included in this repository.

## Public site deployment

GitHub Pages serves `docs/` on the `main` branch. Static public pages need no build dependencies. See `docs/privacy.html` and `docs/terms.html` for current data practices and use terms.

## 训练日与恢复观察模式

可按日期保存「训练／休息／未决定」计划。计划不视为已完成训练；本日有记录时保留实际训练回顾，未同步日期不会被当作休息日。休息或停练观察侧重恢复趋势和最近训练回顾，不凭间隔天数判断充分恢复。趋势分别取最近 7 晚与此前 7 晚的中位数，每段至少需 3 个有效夜晚。日报导出和可选 AI 摘要包含当日计划与模式；更改计划后需手动重新生成已缓存的 AI 日报。
