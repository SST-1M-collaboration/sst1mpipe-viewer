"""
Pages of the accumulated statistics: DL1 Statistics and DL2 Statistics.

The histograms are defined by the statistics configuration of the data level
(`sst1mpipe_viewer.config`). Every row received is accumulated: there is no selection (cuts) in
the viewer, it belongs to the pipeline.
"""

from bokeh.layouts import column, row
from bokeh.models import ColumnDataSource, DataTable, Div, Select, TableColumn

from ..components import Histogram1DPanel, Histogram2DPanel
from ..config import display_options
from ..dl2 import GROUPS, SUBARRAY_ID
from ..store import DL2_KINDS
from ..units import column_unit
from .base import Page

__all__ = ["StatisticsPage"]


def axis_label(name, transform=None, unit=None):
    """Label of an axis of a histogram: ``log10(name)``, or ``name (unit)``"""
    unit = column_unit(name) if unit is None else unit
    if transform:
        return f"{transform}({name})"
    return f"{name} ({unit})" if unit else name


def _grid(panels, n_columns):
    """Panels in rows of ``n_columns``"""
    return column([row(panels[i:i + n_columns]) for i in range(0, len(panels), n_columns)])


def _section(title):
    """Title of a section of the page"""
    return Div(text=f"<h3 style='margin: 10px 0 0 0'>{title}</h3>")


class StatisticsPage(Page):
    """
    Accumulated histograms of a data level for the selected telescopes:

    - the 1D histograms of the telescopes are superimposed, each with the color of its telescope;
    - the 2D histograms (correlations) have one plot per telescope.

    Parameters
    ----------
    session : ViewerSession
        The page of the browser.
    kind : str
        ``"dl1"``, ``"dl2"`` or ``"dl2_stereo"``. The stereo statistics are those of the subarray
        (a single series, `SUBARRAY_ID`), not of the selected telescopes.

    The DL2 are reconstructed by algorithms: the page has one menu per group of quantities
    (geometry, energy, classification, ...) to choose the algorithm whose histograms are shown
    (`sst1mpipe_viewer.dl2`).
    """

    def __init__(self, session, kind="dl1"):
        super().__init__(session)
        self.kind = kind
        self.stereo = kind == "dl2_stereo"
        self.title = "DL2 Stereo Statistics" if self.stereo else f"{kind.upper()} Statistics"
        config = self.store.statistics_configs[kind]
        options = display_options(config)
        all_tel_ids = [SUBARRAY_ID] if self.stereo else session.all_tel_ids
        colors = {tel_id: session.color(tel_id) for tel_id in all_tel_ids}
        labels = {tel_id: session.tel_label(tel_id) for tel_id in all_tel_ids}
        # DL2: the algorithm of each group, chosen in a menu (filled with the algorithms received)
        self.algorithm_selects = {}
        if kind in DL2_KINDS:
            for group in GROUPS:
                select = Select(title=f"{group.capitalize()} algorithm", value="", options=[], width=230,
                                visible=False)
                select.on_change("value", lambda attr, old, new: self._algorithm_changed())
                self.algorithm_selects[group] = select

        self.hist1d = [
            Histogram1DPanel(
                spec.get("name", spec["column"]), title=spec.get("title", spec["column"]),
                x_label=axis_label(spec["column"], spec.get("transform"), spec.get("unit")),
                colors=colors, labels=labels,
                **options[spec.get("name", spec["column"])],
            )
            for spec in config.get("hist1d", ())
        ]
        # 2D histograms: one per telescope
        self.hist2d = {}
        for spec in config.get("hist2d", ()):
            name = spec.get("name", f"{spec['y']}_vs_{spec['x']}")
            for tel_id in all_tel_ids:
                panel = Histogram2DPanel(
                    name, title=f"{spec.get('title') or name} – {labels[tel_id]}",
                    x_label=axis_label(spec["x"], spec.get("x_transform")),
                    y_label=axis_label(spec["y"], spec.get("y_transform")),
                    **options[name],
                )
                panel.figure.title.text_color = colors[tel_id]
                self.hist2d[(name, tel_id)] = panel
        self._hist2d_names = list(dict.fromkeys(name for name, _ in self.hist2d))
        self._snapshots = {}

        # a table, not a Div: changing a Div lays out the whole page again (slow)
        level = "Stereo DL2" if self.stereo else kind.upper()
        self.counters_source = ColumnDataSource(data=dict(tel=[], rows=[]))
        self.counters = DataTable(source=self.counters_source, index_position=None, width=400, height=80, columns=[
            TableColumn(field="tel", title="Telescope", width=100),
            TableColumn(field="rows", title=f"{level} rows accumulated", width=200),
        ])
        self.legend = Div(text="", height=24)
        self.correlations = column()
        self._shown_tel_ids = None

        sections = [
            row(*self.algorithm_selects.values()),
            self.counters,
            self.legend,
            _section("Parameter distributions"),
            _grid([p.layout for p in self.hist1d], 4),
        ]
        if self.hist2d:
            sections += [_section("Correlations"), self.correlations]
        self.layout = column(*sections)

    # ------------------------------------------------------------ algorithms
    def algorithms(self):
        """The algorithms chosen in the menus ``{group: algorithm}`` (empty for the DL1)"""
        return {group: select.value for group, select in self.algorithm_selects.items() if select.value}

    def _update_algorithm_menus(self, tel_ids):
        """Options of the menus: the algorithms received for the telescopes (a menu without algorithm is hidden)"""
        received = {}
        for tel_id in tel_ids:
            for group, names in self.store.algorithms(tel_id, self.kind).items():
                received.setdefault(group, [])
                received[group] += [name for name in names if name not in received[group]]
        for group, select in self.algorithm_selects.items():
            options = received.get(group, [])
            if list(select.options) != options:
                select.options = options
            if options and select.value not in options:
                select.value = options[0]
            if select.visible != bool(options):
                select.visible = bool(options)

    def _algorithm_changed(self):
        """Another algorithm was chosen: its histograms are shown"""
        for panel in (*self.hist1d, *self.hist2d.values()):
            panel.invalidate()
        self.session.request_refresh()

    def _tel_ids(self):
        """The telescopes shown: the selected ones, or the subarray for the stereo statistics"""
        if self.stereo:
            return [SUBARRAY_ID]
        return [t for t in self.session.tel_ids if t in self.session.all_tel_ids]

    # --------------------------------------------------------------- display
    def _set_layout(self, tel_ids):
        """Plots of the selected telescopes (the layout changes only when the selection changes)"""
        if tel_ids == self._shown_tel_ids:
            return
        self._shown_tel_ids = tel_ids
        session = self.session
        self.legend.text = "Telescopes: " + " &nbsp; ".join(
            f"<span style='color: {session.color(t)}; font-weight: bold'>&#9632; {session.tel_label(t)}</span>"
            for t in tel_ids)
        self.correlations.children = [
            row([self.hist2d[(name, t)].layout for t in tel_ids if (name, t) in self.hist2d])
            for name in self._hist2d_names
        ]
        for panel in self.hist1d:
            panel.invalidate()

    def refresh(self):
        """Show the statistics of the selected telescopes"""
        session = self.session
        tel_ids = self._tel_ids()
        self._set_layout(tel_ids)
        self._update_algorithm_menus(tel_ids)
        algorithms = self.algorithms()
        snapshots = {tel_id: self.store.statistics(tel_id, self.kind, algorithms) for tel_id in tel_ids}
        self._snapshots = snapshots
        self.counters_source.data = dict(tel=[session.tel_label(t) for t in tel_ids],
                                         rows=[s["n_rows"] for s in snapshots.values()])
        for panel in self.hist1d:
            panel.update({t: s["accumulators"][panel.name] for t, s in snapshots.items()
                          if panel.name in s["accumulators"]})
        for tel_id, snapshot in snapshots.items():
            for name in self._hist2d_names:
                if name in snapshot["accumulators"] and (name, tel_id) in self.hist2d:
                    self.hist2d[(name, tel_id)].update(snapshot["accumulators"][name])
