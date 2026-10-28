# Security

This is a preview, single-tenant deployment package. Do not operate it as a shared multi-customer service without implementing isolation, authorization, tenant-scoped state, secret storage and independent security review.

Never post credentials, tokens, customer data, private keys, Terraform state/plan, bound.env or provider logs in issues, pull requests or chat. Examples contain placeholders; do not replace them with real values in Git.

Cloud.ru credentials and the MCP bearer are separate. The bearer is pre-issued for a private client, checked by hash/expiry/resource; this project does not implement an interactive OAuth authorization server. Keep TLS validation enabled, protect reverse-proxy logs and restrict network access.

Public disclosure of a suspected vulnerability should contain only a minimal non-sensitive description. Use GitHub private vulnerability reporting if available. If it is unavailable, request a private reporting channel without posting exploit details or secrets. Rotate exposed credentials through the provider immediately; deleting a Git commit is not sufficient.

There is no promise of a response SLA or production security certification. Before deployment, review role scope, dependency versions, network policy, costs, retention and the acceptance checklist.
