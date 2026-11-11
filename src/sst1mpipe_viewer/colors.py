"""Color of each telescope, the same in all the pages (array map, histograms, titles)"""

from bokeh.palettes import Category10_10

__all__ = ["TELESCOPE_COLORS", "telescope_color"]

#: distinguishable colors of the telescopes, in the order of their ids
TELESCOPE_COLORS = Category10_10


def telescope_color(tel_id, tel_ids):
    """Color of a telescope among the telescopes ``tel_ids`` (by its rank in the sorted ids)"""
    ids = sorted(int(t) for t in tel_ids)
    rank = ids.index(int(tel_id)) if int(tel_id) in ids else len(ids)
    return TELESCOPE_COLORS[rank % len(TELESCOPE_COLORS)]
