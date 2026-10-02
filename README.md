# manali-api

The small backend behind [manali-co.github.io](https://github.com/manali-co/manali-co.github.io): subscribers and email. FastAPI on Azure Functions (Flex Consumption), subscribers in Azure Table Storage, email through Resend, telemetry into the Application Insights the org already runs.

Reactions (anonymous, per browser) are here too, in the `reactions` table. Comments are not: they live in GitHub Discussions (giscus on the site), and GitHub emails people when someone replies to them.

## Endpoints

| Method | Path | Who calls it | What it does |
|---|---|---|---|
| `POST` | `/subscribe` | the site's server | Stores a pending address and sends the confirmation email. Always `202`; never says whether an address is on the list. At most one email per ten minutes and three per day per address. |
| `POST` | `/confirm` | the site's `/confirm/` page, after a click | Confirms, sends the welcome email. A GET from a link scanner changes nothing. |
| `POST` | `/unsubscribe` | the site's `/unsubscribe/` page, or the one-click header via the site's `/api/unsubscribe` | Deletes the row and sends the goodbye. Idempotent; the answer never reveals whether the token matched. |
| `GET` | `/admin/stats` | the admin page | Count, pending count, recent confirmed sign-ups, last email sent. Purges addresses that never confirmed within 7 days. Needs `x-admin-key`. |
| `POST` | `/admin/announce` | the admin page, after a confirm step | Emails a post to every confirmed address, one message each, in idempotent batches of 100 with retries. Refuses a slug already announced unless `force`. Needs `x-admin-key`. |
| `GET` | `/admin/telemetry?range=24h\|7d` | the admin page | Visitors and API health from Application Insights, read with the managed identity (Monitoring Reader on a component in this resource group). `/admin/telemetry/now` is just the last five minutes. Needs `x-admin-key`. |
| `GET` | `/admin/data`, `/admin/data/{table}` | the admin page | Every table with its purpose, row count and last change; one table's rows newest first, 50 a page, client ids and confirmation tokens shortened. Needs `x-admin-key`. |
| `GET` | `/healthz` | anyone | `{ok, configured, mail, site_url, problems}` |

Everything except `/healthz` needs the `x-api-key` header, and `/admin/*` needs `x-admin-key` as well. Browsers never hold either; the Next.js server does. Until `MANALI_API_KEY`, `MANALI_TOKEN_SECRET` (32+ characters each), an https `MANALI_SITE_URL` and a tables endpoint are set, every route except `/healthz` answers `503` and `/healthz` lists what is missing.

## Run it locally

```sh
uv sync --extra dev
uv run pytest
cp local.settings.json.example local.settings.json   # then fill in keys
func start
```

With `MANALI_ENV=local` (or `test`) and no `MANALI_TABLES_*`, the store is in memory and email is captured instead of sent. In any other environment a missing Resend key means email is **not** sent and `send` returns 0, never a fake success.

## Settings

| Setting | What |
|---|---|
| `MANALI_ENV` | `dev` / `prod` (set by Bicep). `local` or `test` enables the in-memory store and mailer. |
| `MANALI_API_KEY` | Shared secret with the site. Same value as the site's `API_KEY`. |
| `MANALI_ADMIN_KEY` | Second secret for `/admin/*`. Same value as the site's `ADMIN_API_KEY`, set only on Vercel production. |
| `MANALI_TOKEN_SECRET` | HMAC secret for unsubscribe tokens. Rotate it and every old link stops working. |
| `RESEND_API_KEY` | From resend.com, with a verified sending domain. |
| `MANALI_MAIL_FROM` | `manali apps <hello@yourdomain>` |
| `MANALI_SITE_URL` | Where the site lives; every link in email is built from it. Must be https and must serve `/confirm/` and `/unsubscribe/`, so the Vercel host, never the static Pages host. |
| `MANALI_TABLES_ENDPOINT` | Table endpoint; the function's managed identity reads and writes. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Set by Bicep from the existing component. |
| `MANALI_APPINSIGHTS_APP_ID` | Set by Bicep; the component the admin page's telemetry is read from. |

## Deploy

One workflow, `.github/workflows/deploy.yml`, two GitHub environments:

| | Trigger | Resource group | Function app | App Insights |
|---|---|---|---|---|
| `dev` | every push to `main` | `rg-manali-dev` | `manali-dev-api` | `wsww-dev-appi` |
| `prod` | a published release, or a manual run with `environment=prod` | `rg-manali-prod` | `manali-prod-api` | `wsww-prod-appi` |

Each run signs in with OIDC (`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`), runs `az deployment group create` with `infra/main.bicep`, publishes with `func azure functionapp publish`, then waits for `/healthz` to report `configured: true` and, with the admin key, reads `/admin/stats` through the managed identity. Tests, lint, types and a pinned-requirements check run first. Variables (`APPINSIGHTS_ID`, `SITE_URL`, optional `MAIL_FROM`) and secrets (`MANALI_API_KEY`, `MANALI_ADMIN_KEY`, `MANALI_TOKEN_SECRET`, `RESEND_API_KEY`) are read from the environment first, then the repo, so prod carries its own. The service principal is scoped to the two resource groups; the owner creates the group, the role assignments and the federated credential once (see `SETUP.md` in the site repo). Each environment has its own storage account, so prod starts with empty tables.

## Telemetry

Requests, dependencies (Resend, Table Storage) and exceptions go to Application Insights automatically through the Functions host. The site sends page views and client errors to the same component with `ai.cloud.role = manali-web`, so the Application map shows browser → site → api → Resend in one picture. Useful queries live in the site README.
