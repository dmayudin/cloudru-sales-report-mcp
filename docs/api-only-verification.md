# API-only: результаты разработки 28.10.2026

## Источники

- Официальные схемы Cloud.ru: https://github.com/cloud-ru/evo-terraform/tree/978dfe015eebe09e7fcc04938e9bcd6725ceca8b/reference — ресурсы VPC, subnet, DNS, VM, ClickHouse, Data Platform, BI, bucket; спецификации datasource.
- Установка и API credentials провайдера: https://cloud.ru/docs/terraform-evolution/ug/topics/quickstart — официальное зеркало https://evo-tf-provider-generic.ar.cloud.ru/ .
- Apache Superset REST: https://superset.apache.org/docs/api/ ; поля проверены также по superset/databases/schemas.py, charts/schemas.py и dashboards/schemas.py официального https://github.com/apache/superset . Upstream master не доказывает версию Cloud.ru Managed BI.
- MCP SDK 1.30.0: локально проверены FastMCP transport/auth settings и TokenVerifier; используется resource-bound pre-issued bearer для закрытого клиента, без браузерного OAuth.

## Проверено

- Официальный cloudru/cloud 2.1.5 установлен из зеркала Cloud.ru с проверкой checksum.
- Полный сгенерированный Terraform JSON: validate=true, 0 ошибок, 0 предупреждений. Это проверка схемы, не реальных квот, ролей и API поведения.
- 33 unit/in-process проверки: данные/адаптеры, ограничения плана и проекта, bearer expiry/resource, запрет apply без внешнего approval, отсутствие BI credentials, блокировка повторного POST при частичной публикации, MCP tool schemas. Без локальных приложений, Docker, БД и listening server.
- Ключи не вводились, платные ресурсы не создавались.

## Проверить на первом облачном запуске

1. IAM-права проекта и Data Platform service account; реальные resource IDs и доступные спецификации. Provider API может вернуть несовместимость, которой нет в schema validation.
2. Network DNS, cloud VM reachability, CA/TLS, cloud_admin/cloud_reader роли, приватность bucket и S3 credentials.
3. Bootstrap runtime, HTTPS и настоящий клиентский MCP initialize/list/call через токен. Пока remote protocol e2e не выполнен.
4. Поддерживаемую headless-авторизацию Managed BI. У Cloud.ru IAM и Superset JWT разные назначения; автоматический обмен между ними не реализован, пока не подтверждён контракт. Если провайдер не поддерживает необходимый API-доступ, сценарий Managed BI блокируется; замена продукта требует решения пользователя.
5. ClickHouse driver/URI в BI, создание connection/dataset/chart/dashboard и фактическую сверку chart-data.
6. Источник полного CSV и отдельный scheduled run. Текущий worker не извлекает данные из бизнес-систем.

## Границы

Готов код API-маршрута и bootstrap-шаблон. Не подтверждена возможность полностью headless Managed BI в данном аккаунте. Не обещать, что достаточно одного IAM токена: нужны IAM, S3 credentials и поддерживаемые BI API credentials; инструмент ввода хранит их на сервере. Публичный MCP токен выдаётся отдельно клиенту.

Plan/apply не реализует автоматический billing cutoff. Approval budget фиксирует согласование; стоимость и срок хранения контролируются оператором. Не удалять ресурсы или state автоматически. После сбоя reconcile через API, сохранённый plan/state и ID.
