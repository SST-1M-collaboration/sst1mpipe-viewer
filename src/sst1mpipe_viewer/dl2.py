"""
Column names of the DL2 data (reconstructed energy, particle type and direction).

The viewer shows the DL2 with the column names of sst1mpipe (``/dl2/event/telescope/parameters``):

=================  ==========================================  ===================================
viewer column      sst1mpipe                                   ctapipe (``DataWriter``)
=================  ==========================================  ===================================
``reco_energy``    ``reco_energy`` (TeV)                       ``<algorithm>_tel_energy``
``gammaness``      ``gammaness``                               ``<algorithm>_tel_prediction``
``reco_alt``       ``reco_alt`` (deg)                          ``<algorithm>_tel_alt``
``reco_az``        ``reco_az`` (deg)                           ``<algorithm>_tel_az``
``reco_src_x/y``   ``reco_src_x`` / ``reco_src_y`` (m, camera)  –
=================  ==========================================  ===================================

The ctapipe columns are not copied: the viewer names refer to the same arrays.
"""

__all__ = ["CTAPIPE_SUFFIXES", "add_dl2_aliases"]

#: suffix of a ctapipe telescope DL2 column -> name in the viewer
CTAPIPE_SUFFIXES = {
    "_tel_energy": "reco_energy",
    "_tel_energy_uncert": "reco_energy_uncert",
    "_tel_prediction": "gammaness",
    "_tel_alt": "reco_alt",
    "_tel_az": "reco_az",
}


def add_dl2_aliases(columns):
    """
    Give the DL2 columns of ctapipe the names of sst1mpipe.

    Parameters
    ----------
    columns : dict
        Columns of DL2 rows ``{name: array}``.

    Returns
    -------
    dict
        The same columns, plus the sst1mpipe names of the ctapipe columns (a column of
        sst1mpipe already present is kept).
    """
    aliases = {}
    for name, values in columns.items():
        for suffix, alias in CTAPIPE_SUFFIXES.items():
            if name.endswith(suffix) and alias not in columns and alias not in aliases:
                aliases[alias] = values
    return {**columns, **aliases} if aliases else columns
