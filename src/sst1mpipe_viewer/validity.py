"""
Is a data level of an event *valid*?

An event may reach the viewer with only some of its data levels, or with a level that could not be
computed (e.g. no pixel left after the image cleaning). A level of an event is valid if:

==============  ====================================================================================
level           valid if
==============  ====================================================================================
R0, R1, DL0     the event has a ``waveform``
DL1             the Hillas parameters were computed: ``hillas_intensity`` (or
                ``camera_frame_hillas_intensity``) is finite
DL2, stereo     at least one algorithm has ``is_valid`` true (valid if there is no such flag)
trigger         always
==============  ====================================================================================

Only the valid levels are counted in the rates (`ViewerStore.rate_history`), and the Live mode shows
the last event whose level is valid. To change the rule, change the functions of this module.
"""

import numpy as np

__all__ = ["WAVEFORM_KINDS", "row_is_valid", "valid_rows", "container_is_valid"]

#: levels with waveforms
WAVEFORM_KINDS = ("r0", "r1", "dl0")
#: columns of the Hillas intensity (ctapipe telescope frame, sst1mpipe camera frame)
INTENSITY_COLUMNS = ("hillas_intensity", "camera_frame_hillas_intensity")
#: suffix of the validity flags of the DL2 algorithms
VALID_SUFFIX = "is_valid"


def _is_finite(value):
    """Whether a value is a finite number"""
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def row_is_valid(kind, row):
    """
    Whether a data level of an event is valid (see the module).

    Parameters
    ----------
    kind : str
        The data level (``"r0"``, ``"r1"``, ``"dl0"``, ``"dl1"``, ``"dl2"``, ``"dl2_stereo"``, ``"trigger"``).
    row : dict
        The row of the level of the event ``{column: value}``.
    """
    if kind in WAVEFORM_KINDS:
        return row.get("waveform") is not None
    if kind == "dl1":
        return any(_is_finite(row.get(name)) for name in INTENSITY_COLUMNS)
    if kind in ("dl2", "dl2_stereo"):
        flags = [value for name, value in row.items() if name.endswith(VALID_SUFFIX)]
        return any(bool(np.all(flag)) for flag in flags) if flags else True
    return True


def valid_rows(kind, columns):
    """
    Which rows of a table are valid (`row_is_valid` for every row at once).

    Parameters
    ----------
    kind : str
        The data level.
    columns : dict
        Columns ``{name: array}`` of the rows.

    Returns
    -------
    numpy array of bool
    """
    n = len(next(iter(columns.values()))) if columns else 0
    if kind in WAVEFORM_KINDS:
        return np.full(n, "waveform" in columns)
    if kind == "dl1":
        valid = np.zeros(n, dtype=bool)
        for name in INTENSITY_COLUMNS:
            if name in columns:
                valid |= np.isfinite(np.asarray(columns[name], dtype=float))
        return valid
    if kind in ("dl2", "dl2_stereo"):
        flags = [np.asarray(values, dtype=bool) for name, values in columns.items()
                 if name.endswith(VALID_SUFFIX) and np.ndim(values) == 1]
        return np.any(flags, axis=0) if flags else np.ones(n, dtype=bool)
    return np.ones(n, dtype=bool)


def container_is_valid(kind, container):
    """Whether a R0 / R1 / DL0 container (not yet converted to a row) is valid: it has a waveform"""
    return getattr(container, "waveform", None) is not None
