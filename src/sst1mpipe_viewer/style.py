"""
Look of the viewer, in the style of the SST-1M web site (https://sst1m.space): black background,
light grey text in Roboto, white titles in Poppins, links in light blue.

- `THEME`: the bokeh theme of the documents (figures, axes, legends, color bars);
- `WIDGET_CSS`: the style of the widgets (buttons, menus, tables, ...), set on every bokeh element
  by the theme (the widgets are drawn in a shadow DOM, which the page style does not reach);
- `PAGE_CSS` / `page_stylesheet`: the style of the page itself (background, fonts loaded from
  Google Fonts).

The colors used by the code of the pages are the constants of this module.
"""

from bokeh.models import GlobalInlineStyleSheet
from bokeh.themes import Theme

__all__ = ["BACKGROUND", "PANEL", "TEXT", "MUTED", "HEADING", "LINK", "ERROR", "FOREGROUND", "GRID", "BORDER",
           "TEXT_FONT", "TITLE_FONT", "THEME", "PAGE_CSS", "WIDGET_CSS", "page_stylesheet"]

#: background of the page and of the plots
BACKGROUND = "#000000"
#: background of the widgets and of the tables
PANEL = "#141414"
#: text, secondary text (captions), titles, links, errors
TEXT = "#dddddd"
MUTED = "#9a9a9a"
HEADING = "#ffffff"
LINK = "#75a3d1"
ERROR = "#ff6b6b"
#: lines drawn without a telescope color (e.g. the mean waveform, the marker of the displayed event)
FOREGROUND = "#ffffff"
#: grid lines and borders
GRID = "#2a2a2a"
BORDER = "#3a3a3a"
#: fonts of the SST-1M web site
#: (no quotes in the lists: they are also used in HTML style attributes)
TEXT_FONT = "Roboto, Helvetica, Arial, sans-serif"
TITLE_FONT = "Poppins, Roboto, Helvetica, Arial, sans-serif"

#: style of the page: background and fonts (the fonts of the SST-1M web site, from Google Fonts)
PAGE_CSS = f"""
@import url('https://fonts.googleapis.com/css?family=Poppins:400,600,700|Roboto:300,400,700&display=swap');
html, body {{ background: {BACKGROUND}; color: {TEXT}; font-family: {TEXT_FONT}; }}
"""


def page_stylesheet():
    """The style of the page (`PAGE_CSS`), for a document (a bokeh model belongs to a single document)"""
    return GlobalInlineStyleSheet(css=PAGE_CSS)

#: style of the widgets, inside their shadow DOM (dark inputs, buttons, menus, tables)
WIDGET_CSS = f"""
:host {{ color: {TEXT}; font-family: {TEXT_FONT}; }}
h1, h2, h3, h4 {{ font-family: {TITLE_FONT}; color: {HEADING}; font-weight: 600; }}
a, a:visited {{ color: {LINK}; }}
.bk-input, select.bk-input, input.bk-input {{
    background-color: {PANEL}; color: {TEXT}; border-color: {BORDER};
}}
.bk-input:focus {{ border-color: {LINK}; box-shadow: none; }}
.bk-input-group label, label {{ color: {TEXT}; }}
.bk-btn-default {{ background-color: {PANEL}; color: {TEXT}; border-color: {BORDER}; }}
.bk-btn-default:hover {{ background-color: #262626; border-color: {MUTED}; }}
.bk-btn-default.bk-active {{ background-color: #2e2e2e; border-color: {LINK}; }}
.bk-btn-success.bk-active, .bk-btn-success {{ background-color: #2e7d32; border-color: #2e7d32; color: #fff; }}
.bk-btn-group .bk-btn {{ color: {TEXT}; }}
.bk-slider-title, .bk-slider-value {{ color: {TEXT}; }}
.noUi-target {{ background: #2a2a2a; border-color: {BORDER}; box-shadow: none; }}
.noUi-connect {{ background: {LINK}; }}
.noUi-handle {{ background: #e0e0e0; border-color: {MUTED}; box-shadow: none; }}
.bk-menu {{ background-color: {PANEL}; color: {TEXT}; border-color: {BORDER}; }}
.bk-menu > :hover, .bk-menu > .bk-active {{ background-color: #262626; }}
.slick-header-columns, .slick-header-column, .slick-header {{
    background: {PANEL} !important; color: {HEADING}; border-color: {BORDER} !important;
}}
.slick-row, .slick-row.even, .slick-row.odd {{ background: {BACKGROUND}; color: {TEXT}; }}
.slick-row.odd {{ background: #0c0c0c; }}
.slick-cell {{ border-color: {GRID} !important; }}
.slick-cell.selected, .slick-row.active {{ background: #1d2a36 !important; }}
.bk-data-table, .slick-viewport, .grid-canvas {{ background: {BACKGROUND}; }}
.bk-toolbar {{ background: transparent; }}
.bk-tool-icon {{ filter: invert(0.85); }}
.bk-tooltip, .bk-tooltip-content {{ background-color: {PANEL}; color: {TEXT}; border-color: {BORDER}; }}
"""

THEME = Theme(json={
    "attrs": {
        # the style of the widgets, given to every bokeh element
        "UIElement": {"stylesheets": [WIDGET_CSS]},
        "Plot": {
            "background_fill_color": BACKGROUND,
            "border_fill_color": BACKGROUND,
            "outline_line_color": BORDER,
        },
        "Axis": {
            "axis_line_color": MUTED,
            "major_tick_line_color": MUTED,
            "minor_tick_line_color": MUTED,
            "major_label_text_color": TEXT,
            "major_label_text_font": TEXT_FONT,
            "axis_label_text_color": TEXT,
            "axis_label_text_font": TEXT_FONT,
            "axis_label_text_font_style": "normal",
        },
        "Grid": {"grid_line_color": GRID},
        "Title": {"text_color": HEADING, "text_font": TITLE_FONT},
        "Legend": {
            "background_fill_color": PANEL,
            "background_fill_alpha": 0.8,
            "border_line_color": BORDER,
            "label_text_color": TEXT,
            "label_text_font": TEXT_FONT,
        },
        "ColorBar": {
            "background_fill_color": BACKGROUND,
            "major_label_text_color": TEXT,
            "major_label_text_font": TEXT_FONT,
            "title_text_color": TEXT,
        },
        "LabelSet": {"text_color": TEXT, "text_font": TEXT_FONT},
        "Label": {"text_color": TEXT, "text_font": TEXT_FONT},
    },
})
