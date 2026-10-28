# Облачный runtime и доступ

Реализация находится по runtime_root из installation.json рядом с SKILL.md; в исходном репозитории — в корне пакета. Способ установки описан в INSTALL.md релиза. Не предполагать конкретный домашний каталог или клиент.

По умолчанию сервер использует Streamable HTTP, loopback 127.0.0.1:8000 за HTTPS reverse proxy. Для клиента — `/mcp` и отдельный bearer token. Сервер хранит только SHA-256 MCP-токена и срок действия, проверяет resource и scope. Это закрытое подключение с заранее выданным токеном, не интерактивный OAuth authorization server. Не запускать OAuth через браузер.

Файлы `deploy/`: systemd unit, конфигурация HTTPS proxy, runtime.env.example, deployment.example.json, mcp-client.toml.example и install-on-cloud.sh. Домены, UUID и ключ SSH в примерах — placeholders. Установку выполняет агент на облачной Ubuntu VM. Нужны Python 3.12, venv, Terraform 1.x и TLS reverse proxy; DNS имя и доверенный сертификат подготавливаются при запуске. Публичный доступ VM ограничен server-side CIDR, порт БД наружу не открывается.

`python -m cloudru_mcp.credentials` запускается пользователем в защищённом терминале облачного хоста: getpass без эха, файлы mode 0600, без перезаписи. Создаёт отдельные пароли импортёра/reader и MCP token со сроком 24 часа. Token сохраняется отдельно, не печатается. Не выполняй инструментом чата ввод секретов вместо пользователя. Права файлов и владельцев устанавливает оператор так, чтобы systemd мог читать их.

Cloud.ru ключи: CLOUDRU_KEY_ID, CLOUDRU_KEY_SECRET. S3: CLOUDRU_S3_ACCESS_KEY (tenant_id:key_id), CLOUDRU_S3_SECRET_KEY. MCP: CLOUDRU_MCP_PUBLIC_URL, CLOUDRU_MCP_TOKEN_SHA256, CLOUDRU_MCP_TOKEN_EXPIRES. BI: CLOUDRU_BI_URL, CLOUDRU_BI_API_TOKEN, затем CLOUDRU_BI_SQLALCHEMY_URI (TLS, отдельный reader) или существующий CLOUDRU_BI_DATABASE_ID. Приложение не загружает .env автоматически; EnvironmentFile читает systemd.

Provisioning реализован через официальный cloudru/cloud 2.1.5, зеркало задано в пакете cloudru_mcp/terraform.rc. Это API-провайдер, без browser u-api и без произвольных shell/HCL от агента. CLOUDRU_DEPLOYMENT_FILE — серверный конфиг; CLOUDRU_STATE_DIR — защищённый каталог state, plan и manifest. Terraform state/plan содержат секреты: не отдавать в tools, не публиковать, не коммитить.

approval.json в state-каталоге содержит plan_sha256, budget_rub (>0), expires_at (Unix seconds). Создаёт оператор после согласования конкретного плана и сметы. Это разрешение затрат, не автоматический лимит биллинга. Повторный apply требует нового плана/согласования; при UNKNOWN сначала reconcile. apply-intent.json нельзя удалять без выяснения исхода.

Создание runtime VM входит в шаблон. Первый bootstrap выполняется API-клиентом агента до появления MCP: render template → Terraform plan/approval/apply → upload/install package по проверенному SSH → server credentials → HTTPS → регистрация MCP. После переноса нельзя оставлять два независимых Terraform state: определить единственного владельца и перенести state/lock/manifest в облачный защищённый каталог. Последующий plan должен переиспользовать этот state.

Неизвестное до live-теста: поддерживаемый способ headless-авторизации Managed BI, доступный ClickHouse driver, актуальные роли/спецификации, CA и сетевой доступ. При несовместимости вернуть конкретную ошибку, не объявлять автоматизацию полностью проверенной и не открывать браузер.
