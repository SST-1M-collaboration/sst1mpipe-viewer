"""
DL2 data: the reconstructed energy, particle type and direction of the showers, as defined by the
ctapipe ``DL2Container`` (``event.dl2.tel[tel_id]`` per telescope and ``event.dl2.stereo`` for the
subarray), each reconstructed by one or several algorithms.

Column names
------------
The columns are those of the ctapipe tables (``DataWriter``), prefixed by the algorithm:

- per telescope (``/dl2/event/telescope/<group>/<algorithm>/tel_XXX``): ``<algorithm>_tel_<field>``,
  e.g. ``RandomForestRegressor_tel_energy``, ``HillasReconstructor_tel_impact_distance``;
- stereo (``/dl2/event/subarray/<group>/<algorithm>``): ``<algorithm>_<field>``, e.g.
  ``HillasReconstructor_alt``.

Groups and generic fields
-------------------------
To plot the data whatever the algorithm, the columns of an algorithm are given *generic* names
(`GROUP_FIELDS`), by group:

==================  ==========================================================================
group               generic fields
==================  ==========================================================================
``geometry``        ``alt``, ``az``, ``core_x``, ``core_y``, ``h_max``, ..., and their uncertainties
``energy``          ``energy``, ``energy_uncert``
``classification``  ``prediction`` (the gammaness)
``impact``          ``impact_distance``, ``impact_distance_uncert`` (per telescope only)
``disp``            ``disp_parameter``, ``disp_sign_score`` (per telescope only)
==================  ==========================================================================

plus ``<group>_is_valid`` and ``<group>_goodness_of_fit``. `find_algorithms` finds the algorithms
of each group in columns, `generic_columns` gives the generic columns of a choice of one algorithm
per group. The statistics are accumulated for every combination of algorithms (`combinations`).

The DL2 tables of sst1mpipe (``reco_energy``, ``gammaness``, ``reco_alt``, ``reco_az``) are shown
as the algorithm ``sst1mpipe`` (`add_sst1mpipe_algorithm`).
"""

from itertools import product

__all__ = ["GROUPS", "GROUP_FIELDS", "SUBARRAY_ID", "find_algorithms", "combinations", "combination_key",
           "generic_columns", "add_sst1mpipe_algorithm", "container_row"]

#: pseudo telescope id of the stereo (subarray) data in the store
SUBARRAY_ID = 0

#: groups of DL2 quantities, in the order of the menus
GROUPS = ("geometry", "energy", "classification", "impact", "disp")

#: generic field -> field name in the columns of an algorithm, for each group; the first field of
#: a group is its signature: an algorithm belongs to the group if it has this field
GROUP_FIELDS = {
    "geometry": {name: name for name in (
        "alt", "az", "alt_uncert", "az_uncert", "ang_distance_uncert", "core_x", "core_y", "core_uncert_x",
        "core_uncert_y", "core_tilted_x", "core_tilted_y", "core_tilted_uncert_x", "core_tilted_uncert_y",
        "h_max", "h_max_uncert", "average_intensity")},
    "energy": {"energy": "energy", "energy_uncert": "energy_uncert"},
    "classification": {"prediction": "prediction"},
    "impact": {"impact_distance": "impact_distance", "impact_distance_uncert": "impact_distance_uncert"},
    "disp": {"disp_parameter": "parameter", "disp_sign_score": "sign_score"},
}
#: fields that every reconstruction has, named ``<group>_<field>`` as generic fields
COMMON_FIELDS = ("is_valid", "goodness_of_fit", "telescopes")
#: groups whose algorithms have the common fields (impact and disp come with another reconstruction)
MAIN_GROUPS = ("geometry", "energy", "classification")

#: columns of the DL2 of sst1mpipe -> columns of the pseudo algorithm "sst1mpipe"
SST1MPIPE_COLUMNS = {
    "reco_energy": "sst1mpipe_tel_energy",
    "gammaness": "sst1mpipe_tel_prediction",
    "reco_alt": "sst1mpipe_tel_alt",
    "reco_az": "sst1mpipe_tel_az",
}

_ALL_FIELDS = sorted({field for fields in GROUP_FIELDS.values() for field in fields.values()} | set(COMMON_FIELDS),
                     key=len, reverse=True)


def _split(name, stereo):
    """(algorithm, field) of a DL2 column name, None if it is not one"""
    separator = "_" if stereo else "_tel_"
    for field in _ALL_FIELDS:  # the longest fields first: "alt_uncert" before "alt"
        suffix = separator + field
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)], field
    return None


def find_algorithms(columns, stereo=False):
    """
    Find the algorithms of DL2 columns.

    Parameters
    ----------
    columns : iterable of str
        Column names (or a dict of columns).
    stereo : bool
        Stereo columns (``<algorithm>_<field>``) instead of telescope ones (``<algorithm>_tel_<field>``).

    Returns
    -------
    dict
        ``{group: {algorithm: {generic field: column name}}}``, the groups in the order of `GROUPS`.
    """
    by_algorithm = {}
    for name in columns:
        split = _split(name, stereo)
        if split is not None:
            by_algorithm.setdefault(split[0], {})[split[1]] = name
    result = {}
    for group in GROUPS:
        signature = next(iter(GROUP_FIELDS[group].values()))
        for algorithm, fields in by_algorithm.items():
            if signature not in fields:
                continue
            generic = {name: fields[field] for name, field in GROUP_FIELDS[group].items() if field in fields}
            if group in MAIN_GROUPS:
                generic.update({f"{group}_{field}": fields[field] for field in COMMON_FIELDS if field in fields})
            result.setdefault(group, {})[algorithm] = generic
    return result


def combinations(algorithms):
    """
    All the choices of one algorithm per group.

    Parameters
    ----------
    algorithms : dict
        ``{group: {algorithm: ...}}`` (`find_algorithms`).

    Returns
    -------
    list of dict
        ``{group: algorithm}`` for each combination (a single empty dict without algorithms).
    """
    groups = [group for group in GROUPS if algorithms.get(group)]
    return [dict(zip(groups, choice)) for choice in product(*(algorithms[group] for group in groups))]


def combination_key(combination):
    """Hashable key of a combination ``{group: algorithm}``"""
    return tuple((group, combination[group]) for group in GROUPS if combination.get(group))


def generic_columns(columns, algorithms, combination):
    """
    Columns of a combination of algorithms, with the generic field names.

    Parameters
    ----------
    columns : dict
        DL2 columns ``{name: array}``.
    algorithms : dict
        The algorithms of the columns (`find_algorithms`).
    combination : dict
        ``{group: algorithm}``.

    Returns
    -------
    dict
        ``{generic field: array}`` (the arrays are not copied).
    """
    result = {}
    for group, algorithm in combination.items():
        for generic, name in algorithms.get(group, {}).get(algorithm, {}).items():
            result[generic] = columns[name]
    return result


def add_sst1mpipe_algorithm(columns):
    """
    Give the DL2 columns of sst1mpipe (``reco_energy``, ``gammaness``, ``reco_alt``, ``reco_az``)
    the names of a ctapipe algorithm called ``sst1mpipe`` (the columns are not copied).
    """
    aliases = {alias: columns[name] for name, alias in SST1MPIPE_COLUMNS.items()
               if name in columns and alias not in columns}
    return {**columns, **aliases} if aliases else columns


def container_row(reconstructed, stereo=False):
    """
    Row of the DL2 of an event, with the column names of the ctapipe tables.

    Parameters
    ----------
    reconstructed : ctapipe container
        ``event.dl2.tel[tel_id]`` (``TelescopeReconstructedContainer``) or ``event.dl2.stereo``
        (``ReconstructedContainer``): maps of ``{algorithm: container}`` per group.
    stereo : bool
        Stereo column names (``<algorithm>_<field>``).

    Returns
    -------
    dict
        ``{column name: value}``, empty if nothing was reconstructed.
    """
    row = {}
    for group, algorithm_map in reconstructed.items():
        # the fields of the impact have a prefix, as in the ctapipe tables
        infix = "impact_" if group == "impact" else ""
        for algorithm, container in algorithm_map.items():
            prefix = f"{algorithm}_" if stereo else f"{algorithm}_tel_"
            for field, value in container.items():
                if value is not None and not isinstance(value, dict):
                    row[f"{prefix}{infix}{field}"] = value
    return row
