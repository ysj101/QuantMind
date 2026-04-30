"""IR 発信頻度メタ観察（銘柄別の発信数時系列）."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from quantmind.storage import get_conn


def disclosure_frequency(
    code: str,
    *,
    end: date | None = None,
    days: int = 30,
) -> pd.DataFrame:
    """指定銘柄の直近 ``days`` 日間の日次開示数を返す.

    Returns
    -------
    pandas.DataFrame
        列: ``date``, ``count``。当該期間のすべての日（0件の日も含む）。
    """
    end_d = end or date.today()
    start_d = end_d - timedelta(days=days - 1)
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            "SELECT CAST(disclosed_at AS DATE) AS d, COUNT(*) FROM disclosures "
            "WHERE code=? AND CAST(disclosed_at AS DATE) BETWEEN ? AND ? "
            "GROUP BY d ORDER BY d",
            [code, start_d, end_d],
        ).fetchall()
    counts = {r[0]: int(r[1]) for r in rows}
    all_days = [start_d + timedelta(days=i) for i in range(days)]
    return pd.DataFrame({"date": all_days, "count": [counts.get(d, 0) for d in all_days]})
