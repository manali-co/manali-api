# manali-api

The small backend behind [manali-co.github.io](https://github.com/manali-co/manali-co.github.io): subscribers and email. FastAPI on Azure Functions (Flex Consumption), subscribers in Azure Table Storage, email through Resend, telemetry into the Application Insights the org already runs.

Comments and reactions are **not** here. They live in GitHub Discussions (giscus on the site), and GitHub emails people when someone replies to them.

## Endpoints

| Method | Path | Who calls it | What it does |
|---|---|---|---|
| `POST` | `/subscribe` | the site's server | Stores a pending address, sends the confirmation email. `409` if already confirmed. |
| `GET` | `/confirm?token=` | the link in that email (via the site's `/api/confirm`) | Confirms, sends the welcome email, redirects to `/subscribe/?confirmed=1`. |
| `POST` | `/unsubscribe` | the site's server | Marks the address unsubscribed, sends the goodbye. Token is a per-address HMAC, so links never expire. |
| `GET` | `/admin/stats` | the admin page | Count, recent sign-ups, last email sent. |
| `POST` | `/admin/announce` | the admin page, after a confirm step | Emails the latest post to every confirmed address, one message each. |
| `GET` | `/healthz` | anyone | `{ok, configured}` |

Everything except `/confirm` and `/healthz` needs the `x-api-key` header. Browsers never hold the key; the Next.js server does.

## Run it locally

```sh
uv sync --extra dev
uv run pytest
cp local.settings.json.example local.settings.json   # then fill in keys
func start
```

Without `MANALI_TABLES_*` the store is in-memory; without `RESEND_API_KEY` emails are logged, not sent.

## Settings

| Setting | What |
|---|---|
| `MANALI_API_KEY` | Shared secret with the site. Same value as the site's `API_KEY`. |
| `MANALI_TOKEN_SECRET` | HMAC secret for unsubscribe tokens. Rotate it and every old link stops working. |
| `RESEND_API_KEY` | From resend.com, with a verified sending domain. |
| `MANALI_MAIL_FROM` | `manali apps <hello@yourdomain>` |
| `MANALI_SITE_URL` | Where the site lives; used in links. |
| `MANALI_TABLES_ENDPOINT` | Table endpoint; the function's managed identity reads and writes. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Set by Bicep from the existing component. |

## Deploy

One workflow, `.github/workflows/deploy.yml`, two GitHub environments:

| | Trigger | Resource group | Function app | App Insights |
|---|---|---|---|---|
| `dev` | every push to `main` | `rg-manali-dev` | `manali-dev-api` | `wsww-dev-appi` |
| `prod` | a published release, or a manual run with `environment=prod` | `rg-manali-prod` | `manali-prod-api` | `wsww-prod-appi` |

Each run signs in with OIDC (`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`), runs `az deployment group create` with `infra/main.bicep`, publishes with `func azure functionapp publish`, then curls `/healthz`. Variables (`APPINSIGHTS_ID`, `SITE_URL`, optional `MAIL_FROM`) and secrets (`MANALI_API_KEY`, `MANALI_TOKEN_SECRET`, `RESEND_API_KEY`) are read from the environment first, then the repo, so prod carries its own. The service principal is scoped to the two resource groups; the owner creates the group, the role assignments and the federated credential once (see `SETUP.md` in the site repo). Each environment has its own storage account, so prod starts with empty tables.

## Telemetry

Requests, dependencies (Resend, Table Storage) and exceptions go to Application Insights automatically through the Functions host. The site sends page views and client errors to the same component with `ai.cloud.role = manali-web`, so the Application map shows browser → site → api → Resend in one picture. Useful queries live in the site README.
