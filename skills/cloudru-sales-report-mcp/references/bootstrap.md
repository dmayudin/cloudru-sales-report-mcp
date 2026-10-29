# Bootstrap: порядок действий агента

Однократное создание облачного исполнителя. Пользователь участвует только в шагах из `console-steps.md`; всё ниже выполняет агент из защищённого окружения своего API-клиента (на машине пользователя или у оператора), без браузера и локального сервера. Скрипты лежат в `scripts/bootstrap/` пакета (runtime_root из installation.json). Ориентир по времени: 2–4 часа при исправной платформе; основная часть — ожидание ClickHouse и BI.

## 0. Подготовка (без ключей, без расходов)

1. Проверь, что доступны `python3.12` с httpx/pydantic (venv пакета) и Terraform/OpenTofu с провайдером cloudru/cloud 2.1.5 (`TF_CLI_CONFIG_FILE=cloudru_mcp/terraform.rc`, зеркало работает; lock-файл провайдера только для darwin_arm64/linux_amd64 — при другой платформе `terraform init -upgrade`).
2. Проверь актуальность тарифов (не старше 7 дней) и собери `tariffs.json` по `deploy/tariffs.example.json`: там реальные значения от 28.10.2026, включая платный BI как запасной вариант. Смета считается `cloudru_mcp.costs`.
3. Сгенерируй ssh-ключ bootstrap (`ssh-keygen -t ed25519 -N '' -f <workdir>/mcp_bootstrap_ed25519`) и определи внешний IP пользователя для `admin_cidr`/`client_cidr` (например, `curl -s https://api.ipify.org`), объяснив, что доступ к серверу будет только с этого адреса.

## 1. Ключ пользователя

1. Открой вкладку терминала приложения и запусти `python scripts/connect_cloud.py` из каталога пакета. Попроси пользователя создать личный ключ доступа (console-steps.md, шаг B) и вставить его. Скрипт проверяет ключ в IAM и пишет маркер `bootstrap-connection.json` с путём к файлу 0600.
2. Все дальнейшие вызовы Terraform делай через `scripts/bootstrap/tfrun.py <workdir> …`, API-проверки через `scripts/bootstrap/api.py URL`. Ключ в аргументы, логи и чат не попадает.
3. Через API подтверди проект (`project_hint` в маркере, `cloudru_evolution_organization_project_collection`) и попроси Tenant ID (шаг C).

## 2. Discovery через провайдер (read-only)

Data sources в отдельном каталоге `discovery/`: `compute_zone_collection`, `clickhouse_version_collection` (24.3, 25.8), `clickhouse_specification_collection` (по зоне и версии; минимальная SINGLE_NODE 2 vCPU/16 ГБ), `bi_flavor_collection` (free tier помечен в поле flavor; проверяй, не занят ли он уже в организации), образ Ubuntu 24.04, флейвор VM (lowcost 2 vCPU/4 ГБ достаточно), тип диска SSD. Лог-группа `default`: `GET https://logging.api.cloud.ru/api/v1/{project}/log-groups`. ID кладутся в `deploy/deployment.json`; `service_account_id` оставь `null` — шаблон создаст аккаунт, роли и ключ сам.

## 3. План и единое согласие

1. `python -m cloudru_mcp.render deployment.json main.tf.json`, сгенерируй пароли в `secret.env.json` (`TF_VAR_importer_password`, `TF_VAR_reader_password`, 0600), `tfrun.py deploy init`, `plan -out=approved.tfplan`, `show -json` → проверь, что все действия create.
2. Покажи пользователю смету (сутки / 7 дней / 30 дней, с НДС) и список того, что будет создано, простыми словами. Получи одно согласие, которое явно включает: создание ресурсов в пределах сметы и срок хранения; правило 80/tcp для сертификата; платный BI как запасной вариант с ценой; право отвязать и пересоздать сбойный ресурс один раз. Запиши `approval.json` (plan_sha256, budget_rub, expires_at) и `apply-intent.json`.

## 4. Apply и ожидание

1. `tfrun.py deploy apply approved.tfplan` в фоне. Типичные остановки и лечение — в `troubleshooting.md`: бакет tainted → `untaint`; BI 20301 → платный флейвор; «Saved plan is stale» → новый plan перед apply.
2. ClickHouse: провайдер может вернуть успех до появления хостов или ждать больше 30 минут. Запусти `watch_cluster.py <cluster_id> --minutes 45`. `READY` → продолжай; `STUCK` → не пересоздавай, готовь обращение, остальное делай параллельно.
3. После apply сохрани `terraform output -json` (содержит sensitive ключ сервисного аккаунта) только в 0600.

## 5. Настройка VM

1. Дождись SSH (`vmssh.sh ssh true` с `VM_IP`, `VM_KEY`, `VM_KNOWN_HOSTS`; первый раз получи host key через `ssh-keyscan` и зафиксируй отпечаток в журнале).
2. Собери tgz пакета (cloudru_mcp, deploy, requirements.lock, pyproject.toml, examples, scripts/bootstrap), `vmssh.sh scp` его и `vm-setup.sh`, затем `sudo bash /tmp/vm-setup.sh <ip-с-дефисами>.sslip.io`. Скрипт ставит публичный DNS, OpenTofu как `terraform`, Caddy, venv и systemd unit.
3. Скачай корневой сертификат Cloud.ru (CN «Cloud.ru External Root CA») с официальной страницы документации, проверь отпечаток, положи в `/etc/cloudru-sales/cloudru-root-ca.pem`.
4. Секреты: `stage_secrets.py deploy bootstrap-secrets.json --from-state` (ключ созданного сервисного аккаунта; без `--from-state` — личный ключ, если runtime должен ходить в Data Platform API), `scp` в `/root/`, `sudo python3 /tmp/make_secrets.py --token-days 7`. Файл на стороне агента после копирования удалить.
5. `runtime.env` из `runtime.env.template` (HOST, PROJECT_ID), `deployment.json`, `tariffs.json` → `/etc/cloudru-sales/`; `systemctl enable --now cloudru-sales-mcp`; проверь `curl 127.0.0.1:8000/mcp` → 401 без токена.
6. HTTPS: после правила `acme` — `systemctl restart caddy`, затем `curl https://<host>/mcp` → 401 с валидным сертификатом.
7. Перенеси единственный Terraform state: `main.tf.json`, `terraform.tfstate`, `.terraform.lock.hcl`, `approval.json` → `/var/lib/cloudru-sales` (владелец cloudru-sales, 0600), создай `manifest.json` (data_platform_id, bi_id, clickhouse_id, clickhouse_hosts, bi_internal_host, runtime_vm_id, runtime_public_ip, subnet_id, vpc_id, bucket, service_account_id). Локальную копию state удали после проверки `plan` на сервере → no-op.

## 6. Подключение клиента

Токен из `/etc/cloudru-sales/client-token` (читать через `sudo cat` в файл 0600, не в чат). Claude Code: `claude mcp add -s user --transport http cloudru-sales https://<host>/mcp --header "Authorization: Bearer $(cat token)"`, затем `claude mcp get cloudru-sales` → Connected. Срок токена ограничен (`CLOUDRU_MCP_TOKEN_EXPIRES`); продление — `rotate_token.py` на VM и повторная регистрация. Дальше работа идёт только MCP-инструментами (SKILL.md, «Данные» и «BI»).

## 7. Журнал

В техническом журнале фиксируй: ID всех ресурсов без секретов, время, статусы, стоимость по факту, оставшиеся ограничения (например, ClickHouse ждёт поддержку), отпечатки ключей/сертификатов. Пользователю — короткий итог по форме из `product.md`.
