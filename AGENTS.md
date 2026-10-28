# Agent instructions

For a user asking to install/use this product, start with README.md and INSTALL.md, then skills/cloudru-sales-report-mcp/SKILL.md. Continue onboarding after installation; do not report cloud success from a local check.

For development, keep the runtime API-only and single-tenant. Preserve write gates, scope checks, plan hash/approval, protected state, TLS checks and unknown-outcome reconciliation. Do not add browser fallback or invent Cloud.ru/Superset APIs. Secret input belongs outside chat.

Default tests require no cloud credentials and do not launch a local application/database. Run pytest from the repository root. Cloud changes require a reviewed plan and authorized budget. Documentation must distinguish implemented code, offline tests and live acceptance.

Never commit runtime secrets, customer IDs/data, state, logs or generated plan files. Update prompts and capability/readiness documentation when behavior changes. Do not claim compatibility with an agent that has not been tested.
