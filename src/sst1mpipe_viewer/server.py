"""Bokeh server of the viewer"""

from bokeh.application import Application
from bokeh.application.handlers.function import FunctionHandler
from bokeh.server.server import Server

from .app import PAGES, StateRegistry, make_document

__all__ = ["serve", "make_server"]


def make_server(store, port=5006, address=None, allow_websocket_origin=None, prefix="", **session_options):
    """
    Bokeh server of the viewer on ``store`` (not started), at ``http://<address>:<port>/``: one
    page per data level (`sst1mpipe_viewer.app.PAGES`: ``/`` for the Array page, ``/r0``, ``/r1``,
    ``/dl0``, ``/dl1``, ``/dl1_statistics``, ``/dl2``, ``/dl2_statistics``), the pages of a browser
    sharing their state (selected telescopes, displayed events, selected pixels).
    ``session_options`` are given to the `ViewerSession` of each page (``refresh_period``, ...).
    """
    registry = StateRegistry()

    def application(page):
        """Bokeh application of a page"""
        def handler(doc):
            """Fill the document of a browser opening the page"""
            make_document(store, doc, page=page, registry=registry, **session_options)

        return Application(FunctionHandler(handler))

    applications = {path: application(page) for page, (path, _, _) in PAGES.items()}
    kwargs = dict(port=port, prefix=prefix)
    if address is not None:
        kwargs["address"] = address
    if allow_websocket_origin:
        kwargs["allow_websocket_origin"] = list(allow_websocket_origin)
    return Server(applications, **kwargs)


def serve(store, port=5006, address=None, allow_websocket_origin=None, show=False, prefix="", **session_options):
    """
    Run the viewer on ``store`` until interrupted (blocking: push the data from another thread).
    """
    server = make_server(store, port=port, address=address, allow_websocket_origin=allow_websocket_origin,
                         prefix=prefix, **session_options)
    server.start()
    if show:
        server.io_loop.add_callback(server.show, "/")
    server.io_loop.start()
