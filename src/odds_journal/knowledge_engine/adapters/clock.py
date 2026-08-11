"""Knowledge Engine 时钟适配器。"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta


class SystemClock:
    """系统时钟适配器。"""

    def now(self) -> datetime:
        tz = timezone(timedelta(hours=8))
        return datetime.now(tz).replace(microsecond=0)