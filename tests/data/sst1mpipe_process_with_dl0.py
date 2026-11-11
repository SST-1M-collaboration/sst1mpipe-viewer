"""
``sst1mpipe-process`` (sst1mpipe ProcessorTool) that also writes the DL0 waveforms.

The ctapipe 0.32 ``DataWriter`` writes the R0 and R1 waveforms and the DL1 data, not the DL0
waveforms. This tool runs the same processing as ``sst1mpipe-process`` and writes the DL0
container of each telescope event (``event.dl0.tel[tel_id]``, filled by the ``CameraCalibrator``
of the processing) to ``--dl0-output``, in the same layout as the R1 tables of the ``DataWriter``
(``/dl0/event/telescope/tel_XXX`` with ``obs_id``, ``event_id`` and ``tel_id``).
Needs sst1mpipe, see README.md.

    python sst1mpipe_process_with_dl0.py --input RUN.fits.fz --output RUN.dl1.h5 \
        --dl0-output RUN.dl0.h5 --config sst1mpipe_data_config.json ...
"""

from ctapipe.containers import TelEventIndexContainer
from ctapipe.core.traits import Path
from ctapipe.io import HDF5TableWriter
from sst1mpipe.scripts.sst1mpipe_process_tool import ProcessorTool


class _DL0Writer:
    """Writes the DL0 containers of each event, then calls the DataWriter of the tool"""

    def __init__(self, data_writer, path):
        self._data_writer = data_writer
        self._table_writer = HDF5TableWriter(str(path), mode="w", add_prefix=True)

    def __call__(self, event):
        for tel_id, dl0 in event.dl0.tel.items():
            index = TelEventIndexContainer(obs_id=event.index.obs_id, event_id=event.index.event_id, tel_id=tel_id)
            dl0.prefix = ""
            self._table_writer.write(f"dl0/event/telescope/tel_{tel_id:03d}", [index, dl0])
        self._data_writer(event)

    def finish(self):
        self._table_writer.close()
        self._data_writer.finish()

    def __getattr__(self, name):
        return getattr(self._data_writer, name)


class ProcessorToolWithDL0(ProcessorTool):
    name = "sst1mpipe-process-with-dl0"
    dl0_output = Path(help="Output file of the DL0 waveforms", directory_ok=False).tag(config=True)
    aliases = {**ProcessorTool.aliases, "dl0-output": "ProcessorToolWithDL0.dl0_output"}

    def setup(self):
        super().setup()
        self.writer = _DL0Writer(self.writer, self.dl0_output)


def main():
    ProcessorToolWithDL0().run()


if __name__ == "__main__":
    main()
