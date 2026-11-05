"""
Accumulators of statistics, filled with columns (see `sst1mpipe_viewer.normalize`).

They do not depend on bokeh: ``fill(columns)`` adds the rows of the columns (one row or a
whole table, vectorized), ``reset()`` clears them, ``snapshot()`` gives a copy of their
current state for the display. An accumulator is filled only if its columns are in the
filled columns, so that the rows of any kind of data can be given to every accumulator.
"""

import operator
import re
from abc import ABCMeta, abstractmethod

import numpy as np

__all__ = [
    "Accumulator",
    "Cut",
    "Histogram1D",
    "Histogram2D",
    "CameraAccumulator",
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
    try:
        return TRANSFORMS[name]
    except KeyError:
        raise ValueError(f"Unknown transform {name!r}, known: {[k for k in TRANSFORMS if k]}") from None


def make_bins(bins=50, range=None, edges=None):
    """Bin edges: ``edges`` if given, else ``bins`` bins in ``range``"""
    if edges is not None:
        return np.asarray(edges, dtype=float)
    if range is None:
        raise ValueError("A range (or the bin edges) is required")
    return np.linspace(range[0], range[1], int(bins) + 1)


_CUT_PATTERN = re.compile(r"^\s*([A-Za-z_]\w*)\s*(<=|>=|==|!=|<|>)\s*([-+0-9.eE]+|nan|inf|-inf)\s*$")
_OPERATORS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


class Cut:
    """A selection ``<column> <operator> <number>``, e.g. ``hillas_intensity > 50``"""

    def __init__(self, expression):
        match = _CUT_PATTERN.match(expression)
        if match is None:
            raise ValueError(
                f"Invalid cut {expression!r}: expected '<column> <op> <number>' with op in {list(_OPERATORS)}"
            )
        self.column, self.op, value = match.groups()
        self.value = float(value)
        self._function = _OPERATORS[self.op]

    def __call__(self, columns):
        """Boolean mask of the rows which pass the cut"""
        return self._function(np.asarray(columns[self.column], dtype=float), self.value)

    def __str__(self):
        return f"{self.column} {self.op} {self.value:g}"


class Accumulator(metaclass=ABCMeta):
    """Base class of the accumulators"""

    #: name of the accumulator (unique in a `StatisticsSet`)
    name: str
    #: whether the cuts of the StatisticsSet are applied
    apply_cuts: bool = True

    def __init__(self, name, title=None, apply_cuts=True):
        self.name = name
        self.title = title or name
        self.apply_cuts = apply_cuts
        self.n_entries = 0

    @property
    @abstractmethod
    def columns(self):
        """Columns needed to fill the accumulator"""

    def accepts(self, columns):
        """Whether the accumulator can be filled with these columns"""
        return all(name in columns for name in self.columns)

    def fill(self, columns, mask=None):
        """Fill with the rows of columns (only the rows of ``mask`` if given)"""
        if not self.accepts(columns):
            return
        values = [np.asarray(columns[name]) for name in self.columns]
        if mask is not None:
            values = [v[mask] for v in values]
        if len(values[0]) == 0:
            return
        self._fill(*values)

    @abstractmethod
    def _fill(self, *values):
        pass

    def reset(self):
        self.n_entries = 0
        self._reset()

    @abstractmethod
    def _reset(self):
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
        return (self.column,)

    def _reset(self):
        self.counts = np.zeros(len(self.edges) - 1, dtype=np.int64)
        self.underflow = 0
        self.overflow = 0
        self.n_invalid = 0
        self._sum = 0.0
        self._sum2 = 0.0
        self._n_finite = 0

    def _fill(self, values):
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
        return self._sum / self._n_finite if self._n_finite else np.nan

    @property
    def std(self):
        if not self._n_finite:
            return np.nan
        mean = self.mean
        return float(np.sqrt(max(self._sum2 / self._n_finite - mean**2, 0.0)))

    def snapshot(self):
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
        return (self.x, self.y)

    def _reset(self):
        self.counts = np.zeros((len(self.x_edges) - 1, len(self.y_edges) - 1), dtype=np.int64)

    def _fill(self, x, y):
        x = self._fx(np.asarray(x, dtype=float).ravel())
        y = self._fy(np.asarray(y, dtype=float).ravel())
        self.n_entries += len(x)
        finite = np.isfinite(x) & np.isfinite(y)
        self.counts += np.histogram2d(x[finite], y[finite], bins=(self.x_edges, self.y_edges))[0].astype(np.int64)

    def snapshot(self):
        return dict(x_edges=self.x_edges, y_edges=self.y_edges, counts=self.counts.copy(), n_entries=self.n_entries)


class CameraAccumulator(Accumulator):
    """
    Per pixel accumulation of an image column (rows of shape ``(n_pixels,)``):
    ``mean`` (mean value of each pixel) or ``fraction`` (fraction of the rows in which
    the pixel is true or non zero, e.g. the fraction of the events in which a pixel
    survives the cleaning with ``image_mask``).
    """

    MODES = ("mean", "fraction")

    def __init__(self, name, column, n_pixels, mode="mean", unit="", **kwargs):
        super().__init__(name, **kwargs)
        if mode not in self.MODES:
            raise ValueError(f"Unknown mode {mode!r}, known: {self.MODES}")
        self.column = column
        self.n_pixels = int(n_pixels)
        self.mode = mode
        self.unit = unit
        self._reset()

    @property
    def columns(self):
        return (self.column,)

    def accepts(self, columns):
        value = columns.get(self.column)
        return value is not None and np.ndim(value) == 2 and np.shape(value)[1] == self.n_pixels

    def _reset(self):
        self._sum = np.zeros(self.n_pixels)
        self._n = np.zeros(self.n_pixels, dtype=np.int64)

    def _fill(self, images):
        images = np.asarray(images, dtype=float)
        finite = np.isfinite(images)
        if self.mode == "fraction":
            images = (images != 0).astype(float)
        self._sum += np.where(finite, images, 0.0).sum(axis=0)
        self._n += finite.sum(axis=0)
        self.n_entries += len(images)

    @property
    def values(self):
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(self._n > 0, self._sum / np.maximum(self._n, 1), np.nan)

    def snapshot(self):
        return dict(values=self.values, n_entries=self.n_entries)


class StatisticsSet:
    """
    Set of accumulators sharing the same cuts. ``fill(columns)`` fills every accumulator
    which accepts the columns, the rows being selected by the cuts for the accumulators
    with ``apply_cuts``. Rows without the columns of the cuts do not fill these accumulators
    (they are counted in ``n_without_cut_columns``).
    """

    def __init__(self, accumulators=(), cuts=()):
        self.accumulators = {}
        for accumulator in accumulators:
            self.add(accumulator)
        self.cuts = [c if isinstance(c, Cut) else Cut(c) for c in cuts]
        self.n_rows = 0
        self.n_selected = 0
        self.n_without_cut_columns = 0

    def add(self, accumulator):
        if accumulator.name in self.accumulators:
            raise ValueError(f"Duplicated accumulator name {accumulator.name!r}")
        self.accumulators[accumulator.name] = accumulator

    def __getitem__(self, name):
        return self.accumulators[name]

    def __iter__(self):
        return iter(self.accumulators.values())

    def selection(self, columns):
        """Mask of the rows passing the cuts, None if a column of the cuts is missing"""
        n = len(next(iter(columns.values())))
        mask = np.ones(n, dtype=bool)
        for cut in self.cuts:
            if cut.column not in columns:
                return None
            with np.errstate(invalid="ignore"):
                mask &= cut(columns)
        return mask

    def fill(self, columns):
        accepting = [a for a in self if a.accepts(columns)]
        if not accepting:
            return
        n = len(next(iter(columns.values())))
        mask = self.selection(columns)
        self.n_rows += n
        if mask is None:
            self.n_without_cut_columns += n
        else:
            self.n_selected += int(np.count_nonzero(mask))
        for accumulator in accepting:
            if not accumulator.apply_cuts or not self.cuts:
                accumulator.fill(columns)
            elif mask is not None:
                accumulator.fill(columns, mask)

    def set_cuts(self, cuts):
        """Replace the cuts and reset the accumulators (filled with the previous cuts)"""
        self.cuts = [c if isinstance(c, Cut) else Cut(c) for c in cuts]
        self.reset()

    def reset(self, name=None):
        """Reset one accumulator, or all of them and the counters"""
        if name is not None:
            self.accumulators[name].reset()
            return
        for accumulator in self:
            accumulator.reset()
        self.n_rows = 0
        self.n_selected = 0
        self.n_without_cut_columns = 0

    def snapshot(self):
        return dict(
            accumulators={name: a.snapshot() for name, a in self.accumulators.items()},
            n_rows=self.n_rows,
            n_selected=self.n_selected,
            n_without_cut_columns=self.n_without_cut_columns,
            cuts=[str(c) for c in self.cuts],
        )
