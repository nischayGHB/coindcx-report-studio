# CoinDCX Futures Report Studio

A local, read-only analytics application for CoinDCX Futures transaction history. It authenticates server-side, creates multi-token and single-token reports, converts clean reports into detailed daywise statistics, renders a trading-desk dashboard, and exports CSV/JSON files.

## Security model

- API keys and secrets are sent only to the local Python backend.
- Secrets are held only in process memory and are never written to disk, browser local storage, logs, or report files.
- A random session id is returned to the browser and stored in session storage so a tab refresh can recover the session.
- Logout removes the client and zeroes its secret bytes.
- The app-facing CoinDCX client exposes reporting methods only. There are no create, edit, cancel, transfer, margin, or exit methods.
- The server binds to `127.0.0.1` by default.

This is designed for local use. Do not deploy it publicly without HTTPS, real identity/authentication, a managed secrets system, CSRF protection, rate limiting, and a hardened deployment review.

## Setup

Python 3.10 or newer is required.

```powershell
cd coindcx-report-studio
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Alternative development command:

```powershell
uvicorn backend.main:app --reload --host 127.0.0.1
```

## Workflow

1. Enter a CoinDCX API key and secret, choose INR or USDT, and select **Test connection**.
2. Enter a From/To range using `DD/MM/YY HH:MM:SS` in Asia/Kolkata time. `26/06/26 23:59:59` means 26 June 2026, 23:59:59 IST.
3. Choose a mode:
   - **Multi token:** enter one or more exact futures pairs, such as `B-ETH_USDT, B-SOL_USDT, B-XRP_USDT`.
   - **Single token:** enter one exact pair.
   - **Daily conversion:** rebuild daywise statistics from the latest generated clean report.
4. Review KPIs, six charts, daywise/token/transaction tables, and processing messages.
5. Download the generated CSV and JSON files.

## Report rules

- Date filters are inclusive and are converted from Asia/Kolkata to epoch milliseconds.
- Token matching is exact after whitespace cleanup and uppercase normalization.
- XAU, `liquidate` rows, zero-amount rows, and position ids can be excluded independently.
- The supplied bad/test position id is excluded by default.
- `net_amount = amount - abs(fee_amount)`.
- Estimated trades default to `max(transaction rows // 2, 1)` per day. Daily conversion can instead count transaction rows or unique position ids.
- Funding is detected from `parent_type`/`stage`; the optional heuristic also marks zero-amount, zero-fee rows as funding.
- Crypto Sharpe annualization uses `sqrt(365.25)`.

## Generated files

Each report gets an isolated folder under `backend/outputs/{report_id}/`.

Multi-token reports include:

- `clean_transactions_multi.csv`
- `daywise_stats_multi.csv`
- `token_breakdown_multi.csv`
- `summary_multi.json`

Single-token reports include token-specific clean, daywise, and summary filenames. Daily conversion adds `daywise_stats_converted.csv` and `summary_converted.json` to the original report folder.

## Troubleshooting

- **Authentication rejected:** verify the key/secret, API permissions, system clock, and margin currency. The test uses the read-only Futures transactions endpoint.
- **No rows after filtering:** check the IST range, exact pair spelling, XAU toggle, liquidate toggle, and excluded position ids.
- **CoinDCX timeout/rate limit:** the client retries temporary failures with exponential backoff. Retry later if all attempts fail.
- **Charts unavailable:** the page loads Chart.js from jsDelivr and has a built-in canvas fallback when the CDN is unavailable.
- **Session expired/backend restarted:** reconnect. Credentials are intentionally not persisted.
- **Port 8000 is busy:** run `uvicorn backend.main:app --host 127.0.0.1 --port 8001`.

