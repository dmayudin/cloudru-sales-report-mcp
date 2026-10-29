# Реальный облачный прогон 28–29.10.2026 (обезличенно)

Что подтверждено через API личным ключом пользователя: отдельная VPC с DNS-подсетью и рабочей подсетью, DNS-сервер, security group (22/443 для admin CIDR, 80 для ACME, egress), приватный бакет с версионированием, кластер Data Platform (RUNNING), VM Ubuntu 24.04 с внешним IP; на VM — OpenTofu 1.8.8 как `terraform`, Caddy с сертификатом Let's Encrypt для `<ip>.sslip.io`, MCP-сервис на loopback, клиент Claude Code подключён по HTTPS (20 tools, 401 без токена).

Что не поднялось: Managed ClickHouse — два кластера разных спецификаций и версий остались в DEPLOYING без хостов (внутренняя ошибка API «get kubeconfig … NULL»), удаление через API невозможно; Managed BI — две ошибки 20301 на free tier и зависание на платном флейворе. Data Platform API для сервисного аккаунта отвечает 500/403. Подробности и лечение — в `skills/cloudru-sales-report-mcp/references/troubleshooting.md`.

Стоимость по факту: ≈279 ₽/сутки с НДС при free tier BI; ClickHouse 4 vCPU +≈72 ₽/сутки; платный BI +3,79 ₽/ч. Идентификаторы ресурсов и обращение в поддержку хранятся у оператора пилота, не в репозитории.
