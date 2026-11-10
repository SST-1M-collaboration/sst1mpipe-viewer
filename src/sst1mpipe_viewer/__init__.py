"""
Bokeh viewer of the SST-1M events (R0, R1, DL0, DL1, DL2, DL3) and of the statistics accumulated from them.

The data are pushed to a `ViewerStore` (ctapipe containers, table rows or tables, see
`sst1mpipe_viewer.store`), displayed by the bokeh server started by `serve`.
"""

from .server import serve
from .store import KINDS, ViewerStore

__all__ = ["KINDS", "ViewerStore", "serve"]
