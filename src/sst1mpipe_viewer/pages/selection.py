"""
Selection page: the telescopes shown by all the pages, and the pixels of each telescope.

The telescopes are selected with check boxes (or by a click on the map of the Array page). Each
selected telescope has a panel to select its pixels by groups of the camera (trigger patch,
module, FADC board, CAN node, sector): `sst1mpipe_viewer.pages.pixel_selection`.
"""

from bokeh.layouts import column
from bokeh.models import CheckboxGroup, Div

from .base import Page
from .pixel_selection import PixelSelectionPanel

__all__ = ["SelectionPage"]

HELP = """
<p style="margin: 0; max-width: 700px">
The pages show the data of the telescopes selected here, each with its color. Each telescope has
its own selection of pixels, used by all the pages (waveforms, outlines on the cameras); pixels
can also be selected by a click on any camera (shift+click to select several).
</p>
"""


class SelectionPage(Page):
    """Selection of the telescopes, and of the pixels of each selected telescope"""

    title = "Selection"

    def __init__(self, session):
        super().__init__(session)
        all_tel_ids = session.all_tel_ids
        self._checkbox_tel_ids = all_tel_ids
        self.telescopes = CheckboxGroup(labels=[f"TEL {t}" for t in all_tel_ids],
                                        active=[i for i, t in enumerate(all_tel_ids) if t in session.tel_ids],
                                        inline=True)
        self.telescopes.on_change("active", lambda attr, old, new: self.session.set_tels(
            [self._checkbox_tel_ids[i] for i in new]))
        self.telescope_colors = Div(text=" &nbsp; ".join(
            f"<span style='color: {session.color(t)}; font-weight: bold'>&#9632; TEL {t}</span>" for t in all_tel_ids))
        # one pixel selection per telescope (each telescope has its own selection)
        self.pixel_selections = {}
        self.pixel_container = column()
        self._shown_tel_ids = None
        self.layout = column(
            Div(text="<h3 style='margin: 8px 0 0 0'>Selected telescopes</h3>"),
            Div(text=HELP),
            self.telescopes, self.telescope_colors,
            self.pixel_container,
        )

    def refresh(self):
        """Update the check boxes and the pixel selection of each selected telescope"""
        selected = self.session.tel_ids
        for tel_id in selected:
            if tel_id not in self.pixel_selections:
                self.pixel_selections[tel_id] = PixelSelectionPanel(self.session, tel_id)
        if selected != self._shown_tel_ids:
            self._shown_tel_ids = selected
            self.pixel_container.children = [self.pixel_selections[t].layout for t in selected]
        for tel_id in selected:
            self.pixel_selections[tel_id].refresh()
        active_boxes = [i for i, t in enumerate(self._checkbox_tel_ids) if t in selected]
        if self.telescopes.active != active_boxes:
            self.telescopes.active = active_boxes
