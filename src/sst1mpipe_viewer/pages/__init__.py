"""Pages of the viewer: one web page per data level"""

from .base import Page
from .events import ImageEventPage
from .overview import OverviewPage
from .statistics import StatisticsPage
from .waveforms import WaveformPage

__all__ = ["Page", "ImageEventPage", "OverviewPage", "StatisticsPage", "WaveformPage"]
