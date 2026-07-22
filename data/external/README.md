# External intelligence inputs

All files are optional. Missing files or fields remain `null` and never stop the intelligence build.

- `earnings_calendar.csv`: `ticker,earnings_date,time,source,updated_at`
- `estimate_revisions.csv`: `ticker,asof,eps_revision_30d_pct,revenue_revision_30d_pct,source`
- `guidance.csv`: `ticker,date,direction,metric,low,high,period,source`
- `news.csv`: `ticker,date,headline,url,source,event_type`
- `insider.csv`: `ticker,transaction_date,transaction_type,transaction_value,owner,form,source`
- `holdings_13f.csv`: `ticker,report_date,manager,shares,market_value,position_change_pct,source`

`direction` accepts `RAISED`, `MAINTAINED`, `LOWERED`, `UP`, `FLAT`, `DOWN`.
`transaction_type` accepts `BUY`, `PURCHASE`, `SELL`, `SALE`.

The command layer records coverage separately for each source and blocks a candidate only when a known earnings date is within ±3 calendar days. It does not treat missing data as negative evidence.
