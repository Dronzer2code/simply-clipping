"""P8 battles: pairs of cars within ``battles.within_s`` from the public feed.

Order and gaps come from public data only (``feed/gaps.parquet`` at the line,
positions in ``cars.parquet`` in between). Scaffold (SC-0): signature only.
"""

from __future__ import annotations

import pandas as pd

from simply_clipping.loader import Config, Feed


def battles(feed: Feed, cfg: Config) -> pd.DataFrame:
    """Rows ``time_s, ahead, behind, gap_s`` for every pair within ``battles.within_s``."""
    raise NotImplementedError("SC-5: battles within battles.within_s")
