"""Pages of the viewer: one web page per data level"""

from .array import ArrayPage
from .base import Page
from .events import ImageEventPage
from .statistics import StatisticsPage
from .waveforms import WaveformPage

__all__ = ["Page", "ImageEventPage", "ArrayPage", "StatisticsPage", "WaveformPage"]
