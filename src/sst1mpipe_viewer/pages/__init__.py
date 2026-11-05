"""Pages (tabs) of the viewer"""

from .base import Page
from .dl1 import DL1EventPage, DL1StatisticsPage
from .overview import OverviewPage
from .waveforms import WaveformPage

__all__ = ["Page", "DL1EventPage", "DL1StatisticsPage", "OverviewPage", "WaveformPage"]
