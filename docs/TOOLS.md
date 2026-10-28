# MCP tools

Generated from public tool docstrings; 20 instruments. No tool accepts credentials as arguments. Concrete schemas are returned by MCP tools/list.

## `sales_configuration()`

Read configured scope and missing configuration, without cloud calls or secrets. IDs come from operator settings, not discovery. Use these IDs in cloudru_inspect_resource.

## `sales_estimate_cost(days)`

Calculate the full scenario estimate from dated, server-configured VAT-inclusive tariffs and usage assumptions. Missing/stale prices return total=null, never a misleading partial total. No billing API or spending cutoff.

## `sales_refresh_source()`

Fetch and import one complete CSV from the operator-configured source/ key in the private bucket. No arbitrary URL or cross-account source. Validate before publishing; same snapshot is retry-safe. Configure source.json outside tool arguments.

## `cloudru_deployment_catalog()`

Start read-only Cloud.ru zone/BI flavor/CH version discovery via the official API provider. Returns job ID; poll status. Requires server IAM credentials and Terraform, no browser.

## `cloudru_deployment_plan()`

Plan the operator-configured dedicated network, DNS, S3, ClickHouse and Data Platform BI. No cloud changes. Returns job ID; finished result has immutable plan hash and resource actions. Prices are NOT inferred by Terraform.

## `cloudru_deployment_apply(plan_sha256)`

Create resources from exactly the reviewed plan. Requires enabled writes AND operator-side approval.json binding hash, budget and expiry. Can incur charges. Returns job ID; never blindly retry unknown outcomes. No delete/update/replacement accepted.

## `cloudru_deployment_status(job_id)`

Poll a provisioning job. Returns only safe manifest/status; no raw Terraform state or secrets. Unknown after restart requires reconciliation.

## `cloudru_use_deployed_resources()`

Bind this process to the protected successful deployment manifest. No caller IDs/URLs accepted. Uses existing server credentials; does not grant permissions. Persist manifest with runtime when moving to the new cloud VM.

## `sales_stage_csv(csv_text)`

Stage authorized CSV content on the cloud MCP host. Returns content hash filename and totals. No user-local file needed. Does not upload to S3 or import yet. Do not send customer PII.

## `sales_bi_probe()`

Verify API authentication and configured database access for Managed BI/Superset. Cloud.ru IAM is not assumed to be a Superset API token. No browser fallback.

## `sales_bi_connect()`

Create the scenario's read-only ClickHouse connection through BI REST. URI/reader credentials come only from server settings. Requires a supported ClickHouse driver and API token; no browser fallback.

## `sales_bi_verify(snapshot_id)`

Query the BI dataset via REST and compare actual snapshot ID, rows, revenue and contribution with ClickHouse committed totals. Fails on mismatch; does not inspect visual layout.

## `sales_bi_publish()`

Publish a dataset, channel summary chart and dashboard through Superset REST. Requires supported BI API credentials and a configured ClickHouse connection. Records intent/IDs; partial failure requires reconciliation before retry. Publication does not prove chart query correctness.

## `cloudru_inspect_resource(kind, resource_id)`

Read one allowlisted Cloud.ru resource status. Get resource_id from sales_configuration. Uses public control-plane endpoints; returns no connection secrets. Does not create/change resources.

## `sales_preview_csv(filename)`

Validate a UTF-8 CSV basename inside the configured import directory. No upload. Return hash and exact totals. CSV is a full snapshot in RUB, with signed returns and fees already allocated per line. Use preview hash for upload.

## `sales_list_uploads(limit, cursor)`

List incoming/ objects in the configured private S3 bucket, one page. Follow next_cursor until null. No object content or signed public links returned.

## `sales_upload_csv(filename, expected_snapshot_id)`

Upload the exact CSV approved after preview to private S3 incoming/<sha256>.csv. Requires enabled writes. Repeated content writes the same key; versioned buckets may retain another version. Does not load ClickHouse.

## `sales_prepare_schema()`

Create two scenario tables and the BI current-snapshot view in an EXISTING configured ClickHouse database. IF NOT EXISTS is retry-safe but does not migrate incompatible tables. Requires enabled writes and DDL grants. No cloud provisioning.

## `sales_import_snapshot(snapshot_id)`

Load an uploaded S3 snapshot into ClickHouse, reconcile counts and amounts, then publish its manifest. Run prepare_schema first. Retry only the same hash after unknown outcome. FINAL eliminates duplicate retry rows. Successful new import selects this snapshot for the BI view.

## `sales_report(snapshot_id, group_by, limit)`

Read exact totals and top groups for one committed snapshot. Contribution = net_revenue-net_cogs-fees. Signed returns must already reduce revenue and recovered cost. margin_pct is null at zero revenue. Truncation affects groups only, never totals.

## Scope and errors

Read-only annotations do not replace authorization. Write tools require operator enablement; provisioning also binds to an approved plan hash. A job ID is not success. State/plan/log output is deliberately not returned. AUTH/ACCESS/CONFIG/STALE/UNKNOWN/RECONCILIATION errors require the corresponding correction, not blind retry. BI adapter compatibility and remote protocol acceptance still need live testing.
