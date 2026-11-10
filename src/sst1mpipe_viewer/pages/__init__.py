"""Pages of the viewer: one web page per data level"""

from .array import ArrayPage
from .base import Page
from .dl3 import DL3Page
from .events import ImageEventPage
from .selection import SelectionPage
from .statistics import StatisticsPage
from .stereo import DL2StereoPage
from .waveforms import WaveformPage

__all__ = ["Page", "ImageEventPage", "ArrayPage", "DL2StereoPage", "DL3Page", "SelectionPage", "StatisticsPage",
           "WaveformPage"]
