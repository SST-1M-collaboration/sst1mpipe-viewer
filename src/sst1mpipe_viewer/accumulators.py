"""
Accumulators of statistics, filled with columns (see `sst1mpipe_viewer.normalize`).

They do not depend on bokeh: ``fill(columns)`` adds the rows of the columns (one row or a
whole table, vectorized), ``reset()`` clears them, ``snapshot()`` gives a copy of their
current state for the display. An accumulator is filled only if its columns are in the
filled columns, so that the rows of any kind of data can be given to every accumulator.
"""

from abc import ABCMeta, abstractmethod

import numpy as np

__all__ = [
    "Accumulator",
    "Histogram1D",
    "Histogram2D",
    "StatisticsSet",
    "make_bins",
]

TRANSFORMS = {
    None: lambda x: x,
    "": lambda x: x,
    "log10": lambda x: np.log10(np.where(x > 0, x, np.nan)),
    "abs": np.abs,
}


def _transform(name):
    """Function of a transform name (``None``, ``"log10"``, ``"abs"``) applied to the values before filling"""
    try:
        return TRANSFORMS[name]
    except KeyError:
        raise ValueError(f"Unknown transform {name!r}, known: {[k for k in TRANSFORMS if k]}") from None


def make_bins(bins=50, range=None, edges=None, log=False):
    """
    Bin edges of a histogram.

    Parameters
    ----------
    bins : int
        Number of bins.
    range : (float, float)
        First and last edges.
    edges : array or None
        The edges themselves (``bins`` and ``range`` are then ignored).
    log : bool
        Logarithmic bins (same width on a logarithmic axis): the range must be positive.
    """
    if edges is not None:
        return np.asarray(edges, dtype=float)
    if range is None:
        raise ValueError("A range (or the bin edges) is required")
    if log:
        if not 0 < range[0] < range[1]:
            raise ValueError(f"Logarithmic bins need a positive range, got {tuple(range)}")
        return np.geomspace(range[0], range[1], int(bins) + 1)
    return np.linspace(range[0], range[1], int(bins) + 1)


class Accumulator(metaclass=ABCMeta):
    """Base class of the accumulators"""

    #: name of the accumulator (unique in a `StatisticsSet`)
    name: str

    def __init__(self, name, title=None):
        self.name = name
        self.title = title or name
        self.n_entries = 0

    @property
    @abstractmethod
    def columns(self):
        """Columns needed to fill the accumulator"""

    def accepts(self, columns):
        """Whether the accumulator can be filled with these columns"""
        return all(name in columns for name in self.columns)

    def fill(self, columns):
        """Add the rows of ``columns`` (nothing is done if a needed column is missing)"""
        if not self.accepts(columns):
            return
        values = [np.asarray(columns[name]) for name in self.columns]
        if len(values[0]) == 0:
            return
        self._fill(*values)

    @abstractmethod
    def _fill(self, *values):
        """Add the values of the columns of the accumulator (implemented by each accumulator)"""
        pass

    def reset(self):
        """Forget all the entries"""
        self.n_entries = 0
        self._reset()

    @abstractmethod
    def _reset(self):
        """Set the accumulated state to empty (implemented by each accumulator)"""
        pass

    @abstractmethod
    def snapshot(self):
        """Copy of the state, a dict"""


class Histogram1D(Accumulator):
    """
    Histogram of a column. The entries outside of the bins are counted in
    ``underflow`` / ``overflow``, the non finite values in ``n_invalid``. The mean and
    standard deviation are those of the (transformed) finite values.
    """

    def __init__(self, name, column, bins, transform=None, unit="", **kwargs):
        super().__init__(name, **kwargs)
        self.column = column
        self.edges = np.asarray(bins, dtype=float)
        self.transform = transform
        self._function = _transform(transform)
        self.unit = unit
        self._reset()

    @property
    def columns(self):
        """Columns needed to fill the accumulator"""
        return (self.column,)

    def _reset(self):
        """Set the accumulated state to empty (implemented by each accumulator)"""
        self.counts = np.zeros(len(self.edges) - 1, dtype=np.int64)
        self.underflow = 0
        self.overflow = 0
        self.n_invalid = 0
        self._sum = 0.0
        self._sum2 = 0.0
        self._n_finite = 0

    def _fill(self, values):
        """Add the values of the columns of the accumulator (implemented by each accumulator)"""
        x = self._function(np.asarray(values, dtype=float).ravel())
        finite = np.isfinite(x)
        x = x[finite]
        self.n_entries += len(finite)
        self.n_invalid += int(np.count_nonzero(~finite))
        self.counts += np.histogram(x, bins=self.edges)[0]
        self.underflow += int(np.count_nonzero(x < self.edges[0]))
        self.overflow += int(np.count_nonzero(x > self.edges[-1]))
        self._n_finite += len(x)
        self._sum += float(np.sum(x))
        self._sum2 += float(np.sum(x**2))

    @property
    def mean(self):
        """Mean of the (transformed) finite values"""
        return self._sum / self._n_finite if self._n_finite else np.nan

    @property
    def std(self):
        """Standard deviation of the (transformed) finite values"""
        if not self._n_finite:
            return np.nan
        mean = self.mean
        return float(np.sqrt(max(self._sum2 / self._n_finite - mean**2, 0.0)))

    def snapshot(self):
        """Copy of the accumulated state, for the display"""
        return dict(
            edges=self.edges,
            counts=self.counts.copy(),
            n_entries=self.n_entries,
            underflow=self.underflow,
            overflow=self.overflow,
            n_invalid=self.n_invalid,
            mean=self.mean,
            std=self.std,
        )


class Histogram2D(Accumulator):
    """2D histogram of two columns (``counts[ix, iy]``)"""

    def __init__(self, name, x, y, x_bins, y_bins, x_transform=None, y_transform=None,
                 x_unit="", y_unit="", **kwargs):
        super().__init__(name, **kwargs)
        self.x, self.y = x, y
        self.x_edges = np.asarray(x_bins, dtype=float)
        self.y_edges = np.asarray(y_bins, dtype=float)
        self.x_transform, self.y_transform = x_transform, y_transform
        self._fx, self._fy = _transform(x_transform), _transform(y_transform)
        self.x_unit, self.y_unit = x_unit, y_unit
        self._reset()

    @property
    def columns(self):
        """Columns needed to fill the accumulator"""
        return (self.x, self.y)

    def _reset(self):
        """Set the accumulated state to empty (implemented by each accumulator)"""
        self.counts = np.zeros((len(self.x_edges) - 1, len(self.y_edges) - 1), dtype=np.int64)

    def _fill(self, x, y):
        """Add the values of the columns of the accumulator (implemented by each accumulator)"""
        x = self._fx(np.asarray(x, dtype=float).ravel())
        y = self._fy(np.asarray(y, dtype=float).ravel())
        self.n_entries += len(x)
        finite = np.isfinite(x) & np.isfinite(y)
        self.counts += np.histogram2d(x[finite], y[finite], bins=(self.x_edges, self.y_edges))[0].astype(np.int64)

    def snapshot(self):
        """Copy of the accumulated state, for the display"""
        return dict(x_edges=self.x_edges, y_edges=self.y_edges, counts=self.counts.copy(), n_entries=self.n_entries)


class StatisticsSet:
    """
    The accumulators of a telescope for a data level (e.g. the DL1 histograms). ``fill(columns)``
    gives the rows to every accumulator whose columns are present. There is no selection of the
    rows: the data are shown as they are received (cuts belong to the pipeline, not the viewer).
    """

    def __init__(self, accumulators=()):
        self.accumulators = {}
        for accumulator in accumulators:
            self.add(accumulator)
        self.n_rows = 0

    def add(self, accumulator):
        """Add an accumulator (its name must be unique)"""
        if accumulator.name in self.accumulators:
            raise ValueError(f"Duplicated accumulator name {accumulator.name!r}")
        self.accumulators[accumulator.name] = accumulator

    def __getitem__(self, name):
        return self.accumulators[name]

    def __iter__(self):
        return iter(self.accumulators.values())

    def fill(self, columns):
        """Add the rows of ``columns`` to the accumulators which can use them"""
        accepting = [a for a in self if a.accepts(columns)]
        if not accepting:
            return
        self.n_rows += len(next(iter(columns.values())))
        for accumulator in accepting:
            accumulator.fill(columns)

    def reset(self, name=None):
        """Reset one accumulator, or all of them and the row counter"""
        if name is not None:
            self.accumulators[name].reset()
            return
        for accumulator in self:
            accumulator.reset()
        self.n_rows = 0

    def snapshot(self):
        """Copy of the state of every accumulator, for the display"""
        return dict(accumulators={name: a.snapshot() for name, a in self.accumulators.items()}, n_rows=self.n_rows)
