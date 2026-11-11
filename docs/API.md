# SmartStock RPA — API summary

Generated from the code by `python scripts/gen_api_docs.py`. The full interactive reference (schemas, try-it-out) is
FastAPI's OpenAPI UI at **http://localhost:8000/docs**.

**Conventions**
- Base path `/api/v1`, JSON. Auth: `Authorization: Bearer <access token>` from `POST /auth/login`; refresh with
  `POST /auth/refresh`. The POS endpoint uses `X-API-Key`; one-click approval endpoints use the token in the URL.
- Lists accept `page`, `page_size` (≤ 500) and `sort` (`field` / `-field`) and return `{items, total, page, page_size}`.
- Errors: `{"detail": "...", "code": "..."}` (validation errors add `errors: [{field, message}]`). Invalid workflow
  transitions return **409** `invalid_transition`; missing permission **403** `forbidden`; login rate limit **429**.
- Permission names come from `app/core/permissions.py` (role matrix in the README).


## Ai Insights

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/agent-runs` | insights.read | agent runs |
| GET | `/api/v1/agents` | insights.read | agents |
| POST | `/api/v1/agents/pipeline/run` | agents.run | run pipeline |
| POST | `/api/v1/agents/{name}/run` | agents.run | run agent |
| GET | `/api/v1/expiry` | stock.read | expiry overview |
| GET | `/api/v1/insights/abc-xyz` | insights.read | abc xyz |
| GET | `/api/v1/insights/dead-stock` | insights.read | dead stock |
| GET | `/api/v1/insights/performance` | insights.read | ai performance |
| GET | `/api/v1/models` | insights.read | models |
| GET | `/api/v1/products/{product_id}/forecast` | products.read | product forecast |

## Alerts & Returns

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/alerts` | alerts.read | list alerts |
| GET | `/api/v1/alerts/summary` | alerts.read | alert summary |
| POST | `/api/v1/alerts/{alert_id}/ack` | alerts.write | ack |
| POST | `/api/v1/alerts/{alert_id}/resolve` | alerts.write | resolve |
| GET | `/api/v1/notifications` | any logged-in user | notifications |
| POST | `/api/v1/notifications/read-all` | any logged-in user | mark all |
| GET | `/api/v1/notifications/unread-count` | any logged-in user | unread count |
| POST | `/api/v1/notifications/{notification_id}/read` | any logged-in user | mark read |
| GET | `/api/v1/returns` | returns.manage | list returns |
| POST | `/api/v1/returns` | returns.manage | create return |
| GET | `/api/v1/returns/{return_id}` | returns.manage | get return |
| GET | `/api/v1/returns/{return_id}/pdf` | returns.manage | return pdf |
| POST | `/api/v1/returns/{return_id}/{action}` | returns.manage | return action |

## Auth

| Method | Path | Permission | Purpose |
|---|---|---|---|
| POST | `/api/v1/auth/2fa/disable` | any logged-in user | totp disable |
| POST | `/api/v1/auth/2fa/enable` | any logged-in user | totp enable |
| POST | `/api/v1/auth/2fa/setup` | any logged-in user | totp setup |
| POST | `/api/v1/auth/change-password` | any logged-in user | change password |
| POST | `/api/v1/auth/forgot-password` | public | forgot password |
| POST | `/api/v1/auth/login` | public | login |
| POST | `/api/v1/auth/logout` | any logged-in user | logout |
| GET | `/api/v1/auth/me` | any logged-in user | me |
| PATCH | `/api/v1/auth/me` | any logged-in user | update me |
| POST | `/api/v1/auth/refresh` | public | refresh |
| POST | `/api/v1/auth/reset-password` | public | reset password |

## Health

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/health` | public | DB, Redis, Celery worker and beat status. 503 only when the core (db/redis) is down. |
| GET | `/api/v1/health/live` | public | live |

## Intelligence

| Method | Path | Permission | Purpose |
|---|---|---|---|
| POST | `/api/v1/assistant/chat` | chat.use | chat |
| DELETE | `/api/v1/assistant/history` | chat.use | chat clear |
| GET | `/api/v1/assistant/history` | chat.use | chat history |
| GET | `/api/v1/assistant/status` | any logged-in user | assistant status |
| POST | `/api/v1/ocr/invoice` | invoice.write | Returns a pre-filled invoice for the user to confirm — nothing is saved here. |
| GET | `/api/v1/portal/rfqs` | portal.use | portal rfqs |
| GET | `/api/v1/portal/rfqs/{rfq_id}` | portal.use | portal rfq |
| POST | `/api/v1/portal/rfqs/{rfq_id}/quotes` | portal.use | portal quote |
| POST | `/api/v1/quotes/fetch-email` | rfq.manage | fetch email quotes |
| GET | `/api/v1/quotes/pending` | rfq.manage | pending email quotes |
| POST | `/api/v1/quotes/{quote_id}/reject` | rfq.manage | reject quote |
| POST | `/api/v1/quotes/{quote_id}/use` | rfq.manage | use quote |
| GET | `/api/v1/rfqs` | rfq.manage | list rfqs |
| POST | `/api/v1/rfqs` | rfq.manage | create rfq |
| GET | `/api/v1/rfqs/{rfq_id}` | rfq.manage | get rfq |
| POST | `/api/v1/rfqs/{rfq_id}/close` | rfq.manage | close rfq |
| POST | `/api/v1/simulator` | simulator.use | simulate |

## Master Data

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/categories` | masters.read | list categories |
| POST | `/api/v1/categories` | masters.write | create category |
| DELETE | `/api/v1/categories/{category_id}` | masters.write | delete category |
| PUT | `/api/v1/categories/{category_id}` | masters.write | update category |
| GET | `/api/v1/locations` | masters.read | list locations |
| POST | `/api/v1/locations` | masters.write | create location |
| PUT | `/api/v1/locations/{location_id}` | masters.write | update location |

## Operations

| Method | Path | Permission | Purpose |
|---|---|---|---|
| POST | `/api/v1/integrations/pos/sales` | public | External POS: authenticate with header `X-API-Key: ssk_…` (create keys in Settings → API keys). |
| GET | `/api/v1/sales` | sales.read | list sales |
| POST | `/api/v1/sales` | sales.write | create sale |
| GET | `/api/v1/sales/{sale_id}` | sales.read | get sale |
| GET | `/api/v1/stock-counts` | stock.read | list counts |
| POST | `/api/v1/stock-counts` | stock.move | start count |
| GET | `/api/v1/stock-counts/{count_id}` | stock.read | get count |
| PATCH | `/api/v1/stock-counts/{count_id}` | stock.move | record count |
| POST | `/api/v1/stock-counts/{count_id}/complete` | stock.approve | complete count |
| GET | `/api/v1/transfers` | stock.read | list transfers |
| POST | `/api/v1/transfers` | stock.move | create transfer |
| GET | `/api/v1/transfers/{transfer_id}` | stock.read | get transfer |
| POST | `/api/v1/transfers/{transfer_id}/approve` | stock.approve | approve transfer |
| POST | `/api/v1/transfers/{transfer_id}/cancel` | stock.approve | cancel transfer |
| POST | `/api/v1/transfers/{transfer_id}/dispatch` | stock.move | dispatch transfer |
| POST | `/api/v1/transfers/{transfer_id}/receive` | stock.move | receive transfer |

## Products

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/products` | products.read | list products |
| POST | `/api/v1/products` | products.write | create product |
| DELETE | `/api/v1/products/{product_id}` | products.write | deactivate product |
| GET | `/api/v1/products/{product_id}` | products.read | product detail |
| PUT | `/api/v1/products/{product_id}` | products.write | update product |

## Purchase Orders

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/goods-receipts/{grn_id}/pdf` | po.read | grn pdf |
| POST | `/api/v1/matches/{match_id}/resolve` | match.resolve | resolve |
| GET | `/api/v1/purchase-orders` | po.read | list pos |
| POST | `/api/v1/purchase-orders/from-approved` | po.write | from approved |
| GET | `/api/v1/purchase-orders/{po_id}` | po.read | get po |
| POST | `/api/v1/purchase-orders/{po_id}/cancel` | po.write | cancel |
| POST | `/api/v1/purchase-orders/{po_id}/close` | po.write | close |
| POST | `/api/v1/purchase-orders/{po_id}/grn` | grn.write | receive |
| POST | `/api/v1/purchase-orders/{po_id}/invoices` | invoice.write | add invoice |
| GET | `/api/v1/purchase-orders/{po_id}/pdf` | po.read | po pdf |
| POST | `/api/v1/purchase-orders/{po_id}/send` | po.write | resend |

## Purchasing

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/approval-rules` | purchasing.read | get rules |
| PUT | `/api/v1/approval-rules` | settings.manage | put rules |
| GET | `/api/v1/approval-rules/route` | purchasing.read | preview route |
| GET | `/api/v1/approvals/summary` | any logged-in user | approvals summary |
| GET | `/api/v1/approvals/token/{token}` | public | token info |
| POST | `/api/v1/approvals/token/{token}` | public | use token |
| GET | `/api/v1/purchase-requests` | purchasing.read | list requests |
| POST | `/api/v1/purchase-requests` | purchasing.write | create request |
| POST | `/api/v1/purchase-requests/bulk-approve` | purchasing.approve | bulk approve |
| GET | `/api/v1/purchase-requests/{pr_id}` | purchasing.read | request detail |
| POST | `/api/v1/purchase-requests/{pr_id}/cancel` | purchasing.write | cancel request |
| POST | `/api/v1/purchase-requests/{pr_id}/decide` | purchasing.approve | decide |
| POST | `/api/v1/purchase-requests/{pr_id}/submit` | purchasing.write | submit request |

## Reports

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/backups` | settings.manage | list backups |
| POST | `/api/v1/backups` | settings.manage | create backup |
| GET | `/api/v1/backups/{name}` | settings.manage | download backup |
| POST | `/api/v1/backups/{name}/restore` | settings.manage | restore backup |
| GET | `/api/v1/dashboard` | any logged-in user | Role-based dashboard: management (admin/manager), staff tasks, or the supplier's portal summary. |
| GET | `/api/v1/report-schedules` | reports.read | list schedules |
| POST | `/api/v1/report-schedules` | reports.read | create schedule |
| DELETE | `/api/v1/report-schedules/{schedule_id}` | reports.read | delete schedule |
| PUT | `/api/v1/report-schedules/{schedule_id}` | reports.read | update schedule |
| POST | `/api/v1/report-schedules/{schedule_id}/send` | reports.read | send schedule |
| GET | `/api/v1/reports` | reports.read | list reports |
| GET | `/api/v1/reports/{name}` | reports.read | get report |

## Settings

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/settings` | settings.read | get settings |
| PUT | `/api/v1/settings` | settings.manage | update settings |
| GET | `/api/v1/settings/api-keys` | settings.manage | list api keys |
| POST | `/api/v1/settings/api-keys` | settings.manage | create api key |
| DELETE | `/api/v1/settings/api-keys/{key_id}` | settings.manage | revoke api key |
| GET | `/api/v1/settings/public` | any logged-in user | Non-sensitive values every logged-in user needs (business header, feature flags). |

## Stock

| Method | Path | Permission | Purpose |
|---|---|---|---|
| POST | `/api/v1/stock/adjust` | stock.adjust | adjust |
| GET | `/api/v1/stock/batches` | stock.read | bucket: expired | critical | warning | ok (thresholds from settings). |
| POST | `/api/v1/stock/in` | stock.move | stock in |
| GET | `/api/v1/stock/lookup` | stock.read | Resolve a scanned barcode / SKU / batch QR to the product, batch and current stock. |
| POST | `/api/v1/stock/markdown` | stock.approve | markdown |
| GET | `/api/v1/stock/movements` | stock.read | movements |
| POST | `/api/v1/stock/out` | stock.move | stock out |
| POST | `/api/v1/stock/write-off` | stock.approve | write off |

## Supplier Portal

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/portal/invoices` | portal.use | invoices |
| GET | `/api/v1/portal/orders` | portal.use | orders |
| GET | `/api/v1/portal/orders/{po_id}` | portal.use | order |
| POST | `/api/v1/portal/orders/{po_id}/confirm` | portal.use | confirm |
| POST | `/api/v1/portal/orders/{po_id}/dispatch` | portal.use | dispatch |
| POST | `/api/v1/portal/orders/{po_id}/invoice` | portal.use | Invoice lines default to the PO quantities and prices; `lines` (JSON) overrides them. |
| GET | `/api/v1/portal/orders/{po_id}/pdf` | portal.use | order pdf |
| POST | `/api/v1/portal/orders/{po_id}/reject` | portal.use | reject |
| GET | `/api/v1/portal/summary` | portal.use | summary |

## Suppliers

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/supplier-products` | suppliers.read | list supplier products |
| POST | `/api/v1/supplier-products` | suppliers.write | upsert supplier product |
| DELETE | `/api/v1/supplier-products/{sp_id}` | suppliers.write | delete supplier product |
| GET | `/api/v1/suppliers` | suppliers.read | list suppliers |
| POST | `/api/v1/suppliers` | suppliers.write | create supplier |
| DELETE | `/api/v1/suppliers/{supplier_id}` | suppliers.write | deactivate supplier |
| GET | `/api/v1/suppliers/{supplier_id}` | suppliers.read | supplier detail |
| PUT | `/api/v1/suppliers/{supplier_id}` | suppliers.write | update supplier |

## Tools

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/audit` | audit.read | audit log |
| GET | `/api/v1/audit/entities` | audit.read | audit entities |
| GET | `/api/v1/imports/templates/{entity}` | imports.run | import template |
| GET | `/api/v1/imports/types` | imports.run | import types |
| POST | `/api/v1/imports/upload` | imports.run | import upload |
| POST | `/api/v1/imports/{job_id}/commit` | imports.run | import commit |
| GET | `/api/v1/imports/{job_id}/errors.csv` | imports.run | import errors |
| POST | `/api/v1/imports/{job_id}/preview` | imports.run | import preview |
| POST | `/api/v1/labels/batches` | labels.print | batch labels |
| POST | `/api/v1/labels/products` | labels.print | product labels |

## Users

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/users` | users.manage | list users |
| POST | `/api/v1/users` | users.manage | create user |
| GET | `/api/v1/users/{user_id}` | users.manage | get user |
| PATCH | `/api/v1/users/{user_id}` | users.manage | update user |
