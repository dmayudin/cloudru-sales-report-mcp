# Известные проблемы и что с ними делать

Все пункты наблюдались на реальном проекте Cloud.ru Evolution 28–29.10.2026 (провайдер cloudru/cloud 2.1.5). Сначала проверь, не исправлено ли уже в шаблоне `cloudru_mcp/infra.py`; большинство пунктов там учтено. Диагностические запросы выполняй скриптами `scripts/bootstrap/api.py` (только GET) и `watch_cluster.py`; тело ошибок пользователю не показывай целиком, объясняй словами.

## Managed ClickHouse: кластер навсегда в статусе «Создается» (DEPLOYING)

Симптом: `GET https://clickhouse.api.cloud.ru/v1/clusters/{id}` → `status: DEPLOYING`, `health: HEALTH_UNSPECIFIED`, `hosts: []`; операция создания (`/v1/clusters/{id}/operations`) имеет `done: false`, а `updated_at` замер через 2–3 секунды после `created_at`. База и пользователи при этом могут создаться. Через Terraform создание пользователя падает с внутренней ошибкой `get kubeconfig from kcluster … converting NULL to string`: под кластер не создан базовый Kubernetes-кластер. Воспроизведено дважды: спецификации 2 vCPU/16 ГБ (25.8) и 4 vCPU/16 ГБ (24.3), одна и та же подсеть.

Что делать:
1. Не ждать больше 45 минут: `watch_cluster.py <id> --minutes 45` печатает `STUCK`.
2. Не пересоздавать кластер «ещё раз на другой конфигурации» без явного согласия пользователя: это добавляет ещё один неудаляемый кластер и расходы под вопросом.
3. Удалить кластер нельзя: `DELETE /v1/clusters/{id}` → `FailedPrecondition: service with status DEPLOYING cannot receive any new tasks`. Удаление делает только поддержка.
4. Отвязать кластер от Terraform (`terraform state rm` для cluster/database/users, предварительно скопировав state), чтобы следующий plan не упирался в него.
5. Подготовить обращение по шаблону ниже и попросить пользователя отправить его (см. console-steps.md, шаг F). Если пользователь сотрудник Cloud.ru, предложить внутреннюю эскалацию команде Managed ClickHouse.
6. Пока кластера нет, не обещать срок; остальной pipeline (VM, MCP, BI) можно довести до готовности.

## Managed BI: «Create instance failed» (task status 20301) на бесплатном тарифе

Симптом: Terraform `cloudru_evolution_bi_bi` падает, задача Data Platform завершается с кодом 20301 без деталей; ресурс остаётся tainted. Дважды на free tier flavor (2 vCPU / 4 ГБ).

Что делать: с согласия пользователя переключить `bi_flavor_id` на платный флейвор (в пилоте `c5e918aa-8096-4840-9329-a90def1ac304`, 3,7881 ₽/ч с НДС по тарифу 7.EVO.18), в rendered main.tf.json убрать `lifecycle` у `cloudru_evolution_bi_bi`, сделать `plan -target=cloudru_evolution_bi_bi.sales` (ожидается replace tainted) и apply. Сохранённый plan устаревает после любого другого apply («Saved plan is stale») — планируй непосредственно перед apply. Создание занимает десятки минут; падение на free tier тоже включить в обращение в поддержку.

## Managed BI: сертификат не доверенный, внутренний адрес не резолвится, API-вход закрыт

- Внешний и внутренний адреса BI (`…dataplatform.cloud.ru`) используют цепочку «Cloud.ru Certificate Manager CA → Cloud.ru External Root CA». Браузеры и curl без этого корня отвечают ERR_CERT_AUTHORITY_INVALID / «unable to get local issuer certificate». Пользователь ставит корень по [инструкции Managed BI](https://cloud.ru/docs/managed-bi/ug/topics/guides__root-certificate); сервер MCP получает его через `CLOUDRU_BI_CA_FILE` (bi.py 0.3.1+) и `CLOUDRU_CH_CA_FILE`.
- Сертификат установлен и доверен (`security dump-trust-settings` показывает «Cloud.ru External Root CA»), а Chrome всё равно пишет об ошибке → Chrome запущен до установки; нужен полный выход через Cmd+Q. Проверка без браузера: `/usr/bin/curl -sS -o /dev/null -w '%{http_code}' https://<external-host>/login/` → 200 после установки корня.
- Внутренний адрес (`internal-evobi-…`) не резолвится из рабочей подсети VM даже через Evolution DNS. Для сервера используй внешний адрес (`CLOUDRU_BI_URL=https://external-evobi-…`) с CA-файлом; в manifest `bi_internal_host` тоже можно указать внешний.
- Страница входа предлагает единственного провайдера «Cloud.ru» (OAuth); `POST /api/v1/security/login` с провайдером db отвечает 401 «Not authorized», `GET /api/v1/security/csrf_token/` без сессии — 401. Значит, headless-токена Superset без интерактивного входа нет: `sales_bi_probe` вернёт AUTH, публикацию дашборда делает пользователь в интерфейсе BI по готовой витрине (вход через Cloud.ru), а агент передаёт параметры подключения ClickHouse (хост:8443, база, пользователь sales_reader, secure=true). Браузерный fallback агента запрещён.

## Data Platform API отвечает 500 DP-ERR-X-000 / 403 для сервисного аккаунта

Симптом: `https://dataplatform.api.cloud.ru/v1/clusters|bis|bis/flavors` с токеном сервисного аккаунта → 500 или 403 даже с ролями `dataplatform.admin`, `bi.admin`; с личным ключом пользователя те же запросы работают.

Что делать: bootstrap всегда вести личным ключом доступа пользователя (console-steps.md, шаг B). Сервисный аккаунт нужен только как параметр кластера Data Platform и для долгоживущих ключей сервера; шаблон создаёт его сам (`service_account_id: null`). Если runtime должен вызывать Data Platform API (inspect BI), использовать личный ключ в `secrets.env` и помнить о его сроке.

## Подсеть: 422 при создании

Причина: `subnet_address` ждёт CIDR (`10.77.0.0/24`), плюс обязательны `default_gateway` и `routed_network`. Шаблон исправлен.

## Data Platform: «None of the found DNS servers match subnet_id»

Причина: подсеть кластера Data Platform должна содержать DNS-сервер Evolution DNS и иметь его в `dns_servers`. Поэтому Data Platform, BI и ClickHouse размещены в DNS-подсети, VM — в рабочей. Шаблон исправлен.

## ClickHouse: «replicas_per_shard must be ≥1 and ≤3»

Провайдер отправляет атрибут `replicas` как `replicas_per_shard` (число хостов на шард), хотя описание говорит о «дополнительных репликах». Для одного хоста `replicas=1`. Шаблон исправлен. Доступные версии: 24.3 и 25.8 (data source `cloudru_evolution_clickhouse_version_collection`). Квота физлица: 5 кластеров на организацию.

## Object Storage bucket: ресурс «tainted» после успешного создания

Баг провайдера: после apply у `cloudru_evolution_obs_bucket` неизвестна квота, ресурс помечается tainted при фактически созданном бакете. Решение: `terraform untaint cloudru_evolution_obs_bucket.sales`, затем повторный plan — no-op.

## VM: 422 «Either cloud_init or image_metadata should be set, not both»; нет SSH

Использовать только `cloud_init_userdata` (base64 cloud-config с пользователем `deploy`, ключом и `hostname`). Вариант image_metadata на Ubuntu-24.04 не давал входа по SSH. Удаление VM удаляет и её сетевой интерфейс: при пересоздании создавай интерфейс заново и переназначай внешний IP (адрес сохраняется, если IP-ресурс не удалён). Шаблон исправлен.

## VM: нет DNS, apt/curl не работают

Приватный DNS 10.77.0.10 недоступен из рабочей подсети VM. `vm-setup.sh` ставит drop-in systemd-resolved с публичными резолверами. Не менять `dns_servers` подсети: это сломает Data Platform.

## VM: HashiCorp 404, Terraform не ставится

releases.hashicorp.com и apt-репозиторий HashiCorp отвечают 404 из российских сетей. `vm-setup.sh` ставит OpenTofu 1.8.8 с GitHub с проверкой SHA256 и символической ссылкой `/usr/local/bin/terraform` (провайдер работает через зеркало `cloudru_mcp/terraform.rc`). `CLOUDRU_TERRAFORM_BIN=/usr/local/bin/terraform`.

## HTTPS: Caddy не получает сертификат

Let's Encrypt проверяет домен по HTTP-01 с порта 80 (или TLS-ALPN на 443) с произвольных адресов. Пока 80/tcp открыт только для admin_cidr, в журнале Caddy `challenge failed … Timeout during connect (likely firewall problem)`. Шаблон содержит правило `acme` (80/tcp из 0.0.0.0/0); Caddy отвечает на 80 только ACME и редиректом на HTTPS. Это ослабление периметра нужно явно назвать в едином согласии. После открытия порта `systemctl restart caddy`; сертификат появляется за 1–3 минуты. Имя хоста без своего домена: `<ip-с-дефисами>.sslip.io`. Ошибки ZeroSSL («account pre-registration callback») игнорировать: Caddy переходит к Let's Encrypt сам.

## Terraform: prevent_destroy мешает починить сбойный ресурс

Шаблон ставит `prevent_destroy` всем ресурсам, и повторный render возвращает его. Для замены tainted/сбойного ресурса убирай `lifecycle` только у него в rendered main.tf.json, делай targeted plan/apply, затем снова render. Удаление/замена только с согласия пользователя.

## Классификатор безопасности агента блокирует действие

В Claude Code отдельные команды (создание платного ресурса по новой цене, правило 0.0.0.0/0, удаление облачного ресурса, запуск терминала с секретами) требуют явного согласия пользователя в чате, причём формулировка должна охватывать именно это действие. Собери всё в одно согласие заранее (SKILL.md, «Одно согласие»), а не проси по кусочку.

## Шаблон обращения в поддержку

```text
Тема: Managed ClickHouse: кластер более N часов в статусе DEPLOYING, хосты не выданы; удалить невозможно

Проект: <название>, ID <project_id>. Зона: <zone>. Организация (customer): <customer_id>.

1. Кластер <name>, ID <cluster_id>, создан <UTC время> через Terraform-провайдер cloudru/cloud 2.1.5.
   Спецификация <spec_id> (<vCPU/RAM>, SINGLE_NODE), версия <ver>, 1 шард, 1 реплика, <N> ГБ SSD, keeper EMBEDDED.
   Подсеть <subnet_id> (<cidr>, VPC <vpc_id>), DNS-сервер <dns_id> (<ip>).
   Операция создания <operation_id>: done=false, updated_at <UTC> (не меняется).
   Состояние по API: status DEPLOYING, health HEALTH_UNSPECIFIED, hosts [].
   DELETE /v1/clusters/{id} → FailedPrecondition "service with status DEPLOYING cannot receive any new tasks".
   При создании пользователя API вернул request_id <id>: "get kubeconfig from kcluster: … converting NULL to string".
   Просьба: завершить или удалить кластер, подтвердить, что в DEPLOYING без хостов он не тарифицируется.

2. (если было) Managed BI: Create instance failed (20301) на free tier <flavor_id>, кластер Data Platform <dp_id>, задачи <task_ids>.

3. (если было) Data Platform API для сервисного аккаунта <sa_id> с ролями dataplatform.admin отвечает 500 DP-ERR-X-000 / 403; от личного ключа работает.
```
