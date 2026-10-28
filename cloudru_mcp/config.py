from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import UUID


class SafeError(Exception):
    """An actionable message which contains no upstream body or credentials."""


def identifier(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,62}", value):
        raise SafeError("CONFIG: database identifier is invalid")
    return value


def uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        raise SafeError("INPUT: expected UUID") from None


@dataclass
class Settings:
    project_id: str = ""
    allowed_dp_clusters: tuple[str, ...] = ()
    allowed_bis: tuple[str, ...] = ()
    allowed_ch_clusters: tuple[str, ...] = ()
    import_dir: Path = Path(".")
    bucket: str = ""
    database: str = "sales_report"
    clickhouse_url: str = ""
    clickhouse_user: str = ""
    clickhouse_password: str = field(default="", repr=False)
    clickhouse_ca: str = ""
    allow_loopback_http: bool = False
    allow_writes: bool = False
    key_id: str = field(default="", repr=False)
    key_secret: str = field(default="", repr=False)
    s3_access_key: str = field(default="", repr=False)
    s3_secret_key: str = field(default="", repr=False)

    @classmethod
    def from_env(cls):
        e = os.environ
        def ids(name):
            return tuple(uuid(v.strip()) for v in e.get(name, "").split(",") if v.strip())
        return cls(
            project_id=uuid(e["CLOUDRU_PROJECT_ID"]) if e.get("CLOUDRU_PROJECT_ID") else "",
            allowed_dp_clusters=ids("CLOUDRU_DP_CLUSTER_IDS"),
            allowed_bis=ids("CLOUDRU_BI_IDS"),
            allowed_ch_clusters=ids("CLOUDRU_CH_CLUSTER_IDS"),
            import_dir=Path(e.get("CLOUDRU_IMPORT_DIR", ".")).resolve(),
            bucket=e.get("CLOUDRU_S3_BUCKET", ""),
            database=identifier(e.get("CLOUDRU_CH_DATABASE", "sales_report")),
            clickhouse_url=e.get("CLOUDRU_CH_URL", ""),
            clickhouse_user=e.get("CLOUDRU_CH_USER", ""),
            clickhouse_password=e.get("CLOUDRU_CH_PASSWORD", ""),
            clickhouse_ca=e.get("CLOUDRU_CH_CA_FILE", ""),
            allow_loopback_http=e.get("CLOUDRU_ALLOW_LOOPBACK_HTTP") == "1",
            allow_writes=e.get("CLOUDRU_ALLOW_WRITES") == "1",
            key_id=e.get("CLOUDRU_KEY_ID", ""), key_secret=e.get("CLOUDRU_KEY_SECRET", ""),
            s3_access_key=e.get("CLOUDRU_S3_ACCESS_KEY", ""),
            s3_secret_key=e.get("CLOUDRU_S3_SECRET_KEY", ""),
        )

    def require_write(self):
        if not self.allow_writes:
            raise SafeError("READ_ONLY: operator must enable CLOUDRU_ALLOW_WRITES=1 for approved data writes")

    def ch_endpoint(self):
        u = urlsplit(self.clickhouse_url)
        local = self.allow_loopback_http and u.hostname in ("localhost", "127.0.0.1", "::1")
        if (u.scheme != "https" and not (u.scheme == "http" and local)) or not u.hostname:
            raise SafeError("CONFIG: set CLOUDRU_CH_URL to HTTPS, or an explicitly enabled loopback tunnel")
        if u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
            raise SafeError("CONFIG: ClickHouse URL must contain only scheme, host and port")
        return self.clickhouse_url
