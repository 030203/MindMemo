"""
时间工具 - 统一"存储 UTC → 本地时间"的转换。

背景：DB(尤其 SQLite)落库会丢 tzinfo，存的是 UTC naive 时间。
展示或做"距今几天"这类相对运算前，必须先转成本地时间，否则会有时区偏差。
reminder_service 里已有同款逻辑，这里抽出来供检索类工具共用。
"""
from __future__ import annotations

from datetime import datetime, timezone


def localnow() -> datetime:
    """当前本地朴素时间。"""
    return datetime.now()


def ensure_local(value: datetime | None) -> datetime | None:
    """把存储值转成本地朴素时间。

    - tzinfo 缺失：按 UTC 处理(SQLite 落库丢 tzinfo)，转本地后去掉 tzinfo
    - tzinfo 存在：直接转本地后去掉 tzinfo
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    return value.astimezone().replace(tzinfo=None)


def local_isoformat(value: datetime | None) -> str | None:
    """转本地时间并 isoformat；None 安全。"""
    local = ensure_local(value)
    return local.isoformat() if local else None
