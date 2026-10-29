# Конфигурация

Все значения ниже настраивает агент/оператор, не конечный пользователь. `.env` автоматически не загружается; EnvironmentFile читает systemd. Файлы `.example` содержат placeholders и не являются рабочими настройками.

## Runtime

| Переменная | Назначение |
|---|---|
| CLOUDRU_MCP_TRANSPORT | streamable-http по умолчанию; stdio сохранён для разработки, не пользовательский cloud маршрут |
| CLOUDRU_MCP_PUBLIC_URL | Доверенный HTTPS URL, ровно `/mcp` |
| CLOUDRU_MCP_TOKEN_SHA256 | SHA-256 отдельного MCP bearer; plaintext token передаётся только клиенту |
| CLOUDRU_MCP_TOKEN_EXPIRES | Время истечения Unix seconds |
| CLOUDRU_PROJECT_ID | Разрешённый проект UUID |
| CLOUDRU_ALLOW_WRITES | 0 по умолчанию; 1 после разрешения нужных записей |
| CLOUDRU_STATE_DIR | Защищённый каталог state/jobs/manifest; по умолчанию /var/lib/cloudru-sales |
| CLOUDRU_DEPLOYMENT_FILE | Конфигурация фиксированного шаблона; /etc/cloudru-sales/deployment.json |
| CLOUDRU_TERRAFORM_BIN | Путь к Terraform на исполнителе; /usr/local/bin/terraform |
| CLOUDRU_IMPORT_DIR | Каталог CSV на облачном исполнителе |
| CLOUDRU_TARIFF_FILE | Проверенные тарифы; /etc/cloudru-sales/tariffs.json |
| CLOUDRU_SOURCE_FILE | Регулярный источник; /etc/cloudru-sales/source.json |

## Доступ к сервисам

| Переменные | Назначение и ограничения |
|---|---|
| CLOUDRU_KEY_ID / CLOUDRU_KEY_SECRET | Ключ доступа service account для IAM; не путать со статическим API-ключом или MCP bearer |
| CLOUDRU_DP_CLUSTER_IDS / CLOUDRU_BI_IDS / CLOUDRU_CH_CLUSTER_IDS | Allowlist UUID через запятую для инспекции ресурсов |
| CLOUDRU_S3_BUCKET | Только bucket сценария |
| CLOUDRU_S3_ACCESS_KEY / CLOUDRU_S3_SECRET_KEY | S3 credentials; access key формата tenant_id:key_id |
| CLOUDRU_CH_URL | HTTPS origin, без path/query/credentials; provider hosts должны быть проверены |
| CLOUDRU_CH_DATABASE / CLOUDRU_CH_USER / CLOUDRU_CH_PASSWORD | БД и импортёр; пароль не передаётся в SQL/tool arguments |
| CLOUDRU_CH_CA_FILE | Доверенная CA при необходимости; не отключать TLS verification |
| CLOUDRU_BI_CA_FILE | CA для Managed BI (частная цепочка Cloud.ru); по умолчанию берётся CLOUDRU_CH_CA_FILE |
| CLOUDRU_BI_CH_PASSWORD | Отдельный reader для BI |
| CLOUDRU_BI_URL | Доверенный HTTPS origin Managed BI |
| CLOUDRU_BI_API_TOKEN | Поддерживаемый BI API token; совместимость проверяется live, IAM не подставляется автоматически |
| CLOUDRU_BI_DATABASE_ID | Уже существующее подтверждённое соединение или ID из protected manifest |
| CLOUDRU_BI_SQLALCHEMY_URI | TLS ClickHouse URI reader; секрет, не выводить в чат/state tools |

`CLOUDRU_ALLOW_LOOPBACK_HTTP=1` существует для старых development/tunnel тестов. В облачном маршруте по умолчанию HTTPS с проверкой CA.

## deployment.json

[Пример](../deploy/deployment.example.json). UUID проекта/service account/zone/flavors/specification/log group/tenant/image/disk type получаются из разрешённых API. Поля name/bucket ограничены форматом. network_cidr — приватный IPv4 /16, выделяется агентом без конфликтов. admin_cidr/client_cidr — IPv4 /24 или уже. ssh_public_key — публичный Ed25519 ключ, не private key. bi_external=false по умолчанию; пользовательский маршрут к BI проверяется отдельно.

Нельзя передавать произвольные HCL, endpoint или команду через MCP. Шаблон создаёт только ресурсы этого сценария и запрещает update/delete/replacement в plan guard.

## tariffs.json

[Пример](../deploy/tariffs.example.json) намеренно содержит null вместо выдуманных цен. Обязательны verified_at с timezone и 11 категорий. rate_rub/quantity — конечные неотрицательные числа, unit = hour/month/period, vat_included=true, source_url HTTPS и assumption.

hour умножается на days×24, month — пропорционально days/30, period — как задано для горизонта. Это оценка расходов при выбранных assumptions, не биллинг. Для period количества/объёмы должны соответствовать именно запрошенному периоду. Источник тарифа проверяется оператором, сервер не подтверждает содержимое URL.

## Source и approval

source.json: `{"kind":"s3_object","key":"source/sales.csv"}`. Другие buckets/URL не принимаются. Файл должен быть полным снимком по контракту, не новой порцией строк.

approval.json: `{"plan_sha256":"<reviewed hash>","budget_rub":500,"expires_at":<Unix seconds>}`. Число 500 здесь лишь пример структуры, не рекомендованный бюджет или уже данное согласие. Файл создаёт оператор для согласованного плана. Не размещать его в Git.

## Что защищать

secrets.env, client-token, bound.env, credentials.json, Terraform state/plan, access keys, private SSH key и provider-error.log не публикуются. Секретные файлы — 0600, каталоги state — 0700, правильные владельцы/группы systemd. Скрипты не являются secret vault; машинный пользователь с доступом к файлу способен прочитать его.
