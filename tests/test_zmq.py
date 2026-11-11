"""The live stream of the pipeline (ZMQ), with the sst1mpipe stream module (sst1mpipe.io.zmq_event_stream)"""

import socket
import time
from pathlib import Path

import pytest

pytest.importorskip("sst1mpipe.io.zmq_event_stream", reason="sst1mpipe (with its ZMQ event stream) not installed")

from sst1mpipe_viewer.cli import make_streams, parse_args  # noqa: E402
from sst1mpipe_viewer.dl2 import SUBARRAY_ID  # noqa: E402
from sst1mpipe_viewer.feeds import ZMQFeed, is_zmq_endpoint  # noqa: E402
from sst1mpipe_viewer.publish import FilePublisher  # noqa: E402
from sst1mpipe_viewer.store import ViewerStore  # noqa: E402

DATA = Path(__file__).parent / "data"
TEL_FILES = {21: DATA / "mrk421_tel21.h5", 22: DATA / "mrk421_tel22.h5"}
STEREO_FILE = DATA / "mrk421_stereo.h5"
pytestmark = pytest.mark.skipif(not STEREO_FILE.is_file() or STEREO_FILE.stat().st_size < 1000,
                                reason="Mrk 421 test files not available (git lfs pull)")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until(condition, timeout=10.0):
    end = time.monotonic() + timeout
    while not condition() and time.monotonic() < end:
        time.sleep(0.05)
    return condition()


def stream(path, port, store, tel_ids=None, stereo=True, publish_tel_ids=None):
    """Publish a file to a ZMQFeed of the store bound on the port, return the feed (stopped)"""
    feed = ZMQFeed(f"tcp://127.0.0.1:{port}", store, tel_ids=tel_ids, stereo=stereo).start()
    assert wait_until(lambda: feed.receiver is not None)
    publisher = FilePublisher(path, f"tcp://127.0.0.1:{port}", tel_ids=publish_tel_ids)
    time.sleep(0.5)  # the receiver polls: its subscription reaches the publisher
    publisher.run(rate=2000)
    return feed, publisher


def test_endpoints():
    assert is_zmq_endpoint("tcp://*:5561") and is_zmq_endpoint("ipc:///tmp/x")
    assert not is_zmq_endpoint("tests/data/mrk421_tel21.h5")
    from ctapipe.instrument import SubarrayDescription

    store = ViewerStore(SubarrayDescription.from_hdf(STEREO_FILE))
    streams = make_streams(parse_args(["--tel1", "tcp://*:5561", "--tel2", "tcp://*:5562"]), store)
    feeds = [feed for _, stream_feeds in streams for feed in stream_feeds]
    assert all(isinstance(feed, ZMQFeed) for feed in feeds)
    assert [(feed.url, feed.tel_ids, feed.stereo) for feed in feeds] == [("tcp://*:5561", {21}, False),
                                                                       ("tcp://*:5562", {22}, False)]


def test_mono_stream():
    """A telescope stream: all its events are received and accumulated, its levels displayed"""
    store = ViewerStore()
    feed, publisher = stream(TEL_FILES[22], free_port(), store, tel_ids=[22], stereo=False)
    try:
        assert wait_until(lambda: store.counts().get((22, "dl1"), 0) == 22)
        assert store.counts()[(22, "trigger")] == 22 and store.counts()[(22, "r1")] == 22
        assert store.statistics(22)["n_rows"] == 22 and store.statistics(22, "dl2")["n_rows"] == 22
        assert feed.receiver.received == 22 and not feed.receiver.lost
        assert store.streams[feed.url] is feed.receiver
        key = store.latest_key(22)
        event = store.event(22, key)
        assert {"trigger", "r0", "r1", "dl0", "dl1", "dl2"} <= set(event)
        assert event["r0"]["waveform"].shape == (1, 1296, 50) and "RandomForestRegressor_tel_energy" in event["dl2"]
        assert store.event_time(22, key) is not None
        times, rates, _ = store.rate_history(22, "trigger")
        assert rates.sum() > 0
    finally:
        feed.stop()
        publisher.close()


def test_stereo_stream():
    """A stream of array events: the telescopes and the stereo DL2; a mono stream ignores the stereo"""
    store = ViewerStore()
    feed, publisher = stream(STEREO_FILE, free_port(), store)
    try:
        assert wait_until(lambda: store.counts().get((21, "dl1"), 0) == 22 and store.counts().get((22, "dl1"), 0) == 22
                          and store.statistics(SUBARRAY_ID, "dl2_stereo")["n_rows"] == 22)
        assert store.event_tel_ids == [21, 22, SUBARRAY_ID]
    finally:
        feed.stop()
        publisher.close()
    mono = ViewerStore()
    feed, publisher = stream(STEREO_FILE, free_port(), mono, tel_ids=[21], stereo=False)
    try:
        assert wait_until(lambda: mono.counts().get((21, "dl1"), 0) == 22)
        time.sleep(0.3)
        assert (22, "dl1") not in mono.counts() and SUBARRAY_ID not in mono.event_tel_ids
    finally:
        feed.stop()
        publisher.close()
