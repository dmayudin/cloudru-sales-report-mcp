# Installation instructions for any agent

User intent: install this skill, then guide a nontechnical user to a Cloud.ru sales report. Do not deploy or request credentials merely because this package was installed.

1. Inspect the trusted repository/release and pinned revision. Read `skills/cloudru-sales-report-mcp/SKILL.md`. A release ZIP contains a SHA-256 file manifest; this detects corruption, not publisher identity.
2. Detect the current agent's documented skill mechanism and supported MCP transport. Do not assume Codex paths for Claude Code or Hermes. If the agent cannot load SKILL.md or connect to remote MCP with a bearer secret, explain the specific capability gap. Never invent a supported client configuration.
3. Use the agent's own installer if available. Otherwise, the agent may run `python3 scripts/install_skill.py --skill-dir <agent's exact skill directory> --runtime-dir <agent-managed package directory>`. Python stdlib only; no pip, server or cloud calls. The user should not have to type commands or select technical paths. Existing installations are not overwritten automatically.
4. The installer writes `installation.json` next to SKILL.md to locate runtime files independently of this repository's path. For a native skill installer, preserve supporting references and place this marker after locating/copying the runtime package. Installing just a raw SKILL.md URL is insufficient: fetch the whole pinned skill folder and package.
5. Continue immediately with the short first message in `references/onboarding.md`. Do not finish with only “skill installed”. Use references/first-time-cloud.md for screen-by-screen guidance and references/access-roles.md before assigning roles. Do not compress setup into “create an account and assign required roles”. No secret collection in chat.

Two runtime delivery modes:

- An operator-provided remote MCP endpoint: validate provider identity, per-customer scope, secure onboarding and token handling before recommending it. This release does NOT include an already running shared endpoint. Current server is single-project/single-tenant: never put multiple unrelated customers on one process/state/token.
- A dedicated Cloud.ru MCP per customer: the agent performs the one-time API bootstrap, costs included in the estimate. No local application launch. Credentials must first be supplied through a trusted agent secret mechanism or user-controlled protected prompt for the management client; after bootstrap transfer them to the cloud executor and remove temporary copies with user-approved handling.

Clients that cannot expose a private input/secret store must not ask the user to paste secrets into conversation. Explain the available secure handoff or stop at connection setup. The provided terminal helper is a fallback, not a hosted onboarding page.

After installation the user deals with account access, data, report mode and cost. Server IDs, Terraform, VM sizing, state migration, package installation and MCP configuration are the agent/operator's work.
