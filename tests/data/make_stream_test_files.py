"""
Split the Mrk 421 file of the two telescopes (written by ``make_mrk421_test_file.py``, with the
synthetic DL2 of ``scripts/make_synthetic_dl2.py``) into the test files of the streams of the viewer:

- ``mrk421_tel21.h5`` and ``mrk421_tel22.h5``: one file per telescope (mono streams), with the
  data of this telescope only (R0, R1, DL0, DL1, synthetic telescope DL2) and no stereo data;
- ``mrk421_stereo.h5``: a stream of complete array events. The two telescopes did not observe the
  same showers in these runs, so the array events are EMULATED: the i-th event of TEL 22 is paired
  with the i-th event of TEL 21 and takes its ``obs_id``, ``event_id`` and time. The file has the
  data of both telescopes for these events, a subarray trigger and a synthetic stereo DL2.

Usage::

    python make_stream_test_files.py mrk421_tel21_tel22.h5 --output-dir .
"""

import argparse
import importlib.util
from pathlib import Path

import numpy as np
import tables
from ctapipe.io import read_table, write_table

TEL_IDS = (21, 22)
#: columns with the time of an event in the telescope tables
TIME_COLUMNS = ("time", "event_time")
SYNTHETIC_NOTE = "Emulated array events (tests/data/make_stream_test_files.py): NOT coincident showers"


def _synthetic_dl2_module():
    """The module ``scripts/make_synthetic_dl2.py`` (for its synthetic stereo tables)"""
    path = Path(__file__).resolve().parents[2] / "scripts" / "make_synthetic_dl2.py"
    spec = importlib.util.spec_from_file_location("make_synthetic_dl2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_file(source, output, keep):
    """Copy the nodes of an HDF5 file whose path is accepted by ``keep(path)``, and the metadata of the file"""
    with tables.open_file(source) as src, tables.open_file(output, "w") as dst:
        src.root._v_attrs._f_copy(dst.root)
        for node in src.walk_nodes("/", "Leaf"):
            if keep(node._v_pathname):
                parent = node._v_parent._v_pathname
                src.copy_node(node, newparent=dst.create_group(*_split(parent), createparents=True)
                              if parent not in dst else dst.get_node(parent))


def _split(path):
    """(parent, name) of an HDF5 path"""
    parent, name = path.rsplit("/", 1)
    return parent or "/", name


def replace_rows(h5file, path, rows):
    """Replace the rows of a table (a structured array), keeping its attributes (the ctapipe metadata)"""
    node = h5file.get_node(path)
    attributes = {name: node.attrs[name] for name in node.attrs._v_attrnamesuser}
    parent, name = _split(path)
    filters, title = node.filters, node.title
    h5file.remove_node(path)
    table = h5file.create_table(parent, name, obj=rows, filters=filters, title=title)
    for key, value in attributes.items():
        table.attrs[key] = value


def other_telescope(path, tel_id):
    """Whether a node is the table of another telescope than ``tel_id``"""
    return any(path.endswith(f"tel_{other:03d}") for other in TEL_IDS if other != tel_id)


def is_stereo(path):
    """Whether a node is a stereo (subarray) event table"""
    return path.startswith(("/dl2/event/subarray", "/dl1/event/subarray"))


def write_telescope_file(source, output, tel_id):
    """The file of the stream of a telescope: its data only, no stereo data"""
    copy_file(source, output, lambda path: not other_telescope(path, tel_id) and not is_stereo(path))
    with tables.open_file(output, "a") as f:
        trigger = f.get_node("/dl1/event/telescope/trigger").read()
        replace_rows(f, "/dl1/event/telescope/trigger", trigger[trigger["tel_id"] == tel_id])


def write_stereo_file(source, output, n_events, seed):
    """The file of emulated array events (see the module)"""
    copy_file(source, output, lambda path: not is_stereo(path))
    first, second = TEL_IDS
    with tables.open_file(output, "a") as f:
        trigger = f.get_node("/dl1/event/telescope/trigger").read()
        # the events of the pairs: the first events of each telescope, in the order of the trigger table
        ids = {tel_id: trigger["event_id"][trigger["tel_id"] == tel_id][:n_events] for tel_id in TEL_IDS}
        n_events = min(len(ids[first]), len(ids[second]))
        ids = {tel_id: values[:n_events] for tel_id, values in ids.items()}
        obs_id = trigger["obs_id"][trigger["tel_id"] == first][0]
        new_id = dict(zip(ids[second].tolist(), ids[first].tolist()))

        def pair(rows_first, rows_second):
            """Rows of the paired events: those of the second telescope take the ids and times of the first"""
            rows_first = rows_first[np.isin(rows_first["event_id"], ids[first])]
            rows_second = rows_second[np.isin(rows_second["event_id"], ids[second])].copy()
            rows_second["event_id"] = [new_id[i] for i in rows_second["event_id"].tolist()]
            rows_second["obs_id"] = obs_id
            position = {event_id: i for i, event_id in enumerate(rows_first["event_id"].tolist())}
            order = [position[i] for i in rows_second["event_id"].tolist()]
            for name in TIME_COLUMNS:
                if name in rows_first.dtype.names:
                    rows_second[name] = rows_first[name][order]
            return rows_first, rows_second

        rows_first, rows_second = pair(trigger[trigger["tel_id"] == first], trigger[trigger["tel_id"] == second])
        replace_rows(f, "/dl1/event/telescope/trigger", np.concatenate([rows_first, rows_second]))
        paths = [node._v_pathname for node in f.walk_nodes("/", "Table")]
        for path in paths:
            if "/event/telescope/" in path and path.endswith(f"tel_{first:03d}"):
                other = path[:-3] + f"{second:03d}"
                rows_first, rows_second = pair(f.get_node(path).read(), f.get_node(other).read())
                replace_rows(f, path, rows_first)
                replace_rows(f, other, rows_second)

    # subarray trigger and synthetic stereo DL2 of the array events
    trigger = read_table(output, "/dl1/event/telescope/trigger")
    trigger = trigger[trigger["tel_id"] == first]
    stereo, stereo_trigger = _synthetic_dl2_module().stereo_tables(
        np.asarray(trigger["obs_id"]), np.asarray(trigger["event_id"]), trigger["time"], len(TEL_IDS),
        np.random.default_rng(seed))
    for (group, algorithm), table in stereo.items():
        write_table(table, output, f"/dl2/event/subarray/{group}/{algorithm}", overwrite=True)
    write_table(stereo_trigger, output, "/dl1/event/subarray/trigger", overwrite=True)
    with tables.open_file(output, "a") as f:
        f.root.dl2._v_attrs.SYNTHETIC = "Random values (scripts/make_synthetic_dl2.py): NOT reconstructed data"
        f.root.dl1.event._v_attrs.SYNTHETIC = SYNTHETIC_NOTE
    # the rows removed still take space in the file: copy it to reclaim it
    repacked = Path(str(output) + ".repacked")
    tables.copy_file(str(output), str(repacked), overwrite=True)
    repacked.replace(output)
    return n_events


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="file of the two telescopes, with the synthetic telescope DL2")
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    parser.add_argument("--n-stereo-events", type=int, default=22, help="number of emulated array events")
    parser.add_argument("--seed", type=int, default=421)
    args = parser.parse_args()
    for tel_id in TEL_IDS:
        output = args.output_dir / f"mrk421_tel{tel_id}.h5"
        write_telescope_file(args.input, output, tel_id)
        with tables.open_file(output, "a") as f:
            f.root.dl2._v_attrs.SYNTHETIC = "Random values (scripts/make_synthetic_dl2.py): NOT reconstructed data"
        print(f"{output}: {output.stat().st_size / 1e6:.1f} MB")
    output = args.output_dir / "mrk421_stereo.h5"
    n_events = write_stereo_file(args.input, output, args.n_stereo_events, args.seed)
    print(f"{output}: {n_events} emulated array events, {output.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
