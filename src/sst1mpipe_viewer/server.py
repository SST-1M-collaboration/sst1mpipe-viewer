"""Bokeh server of the viewer"""

from bokeh.application import Application
from bokeh.application.handlers.function import FunctionHandler
from bokeh.server.server import Server

from .app import make_document

__all__ = ["serve", "make_server"]


def make_server(store, port=5006, address=None, allow_websocket_origin=None, prefix="", **session_options):
    """
    Bokeh server of the viewer on ``store`` (not started), at ``http://<address>:<port>/``.
    ``session_options`` are given to the `ViewerSession` of each browser (``refresh_period``, ...).
    """
    def handler(doc):
        make_document(store, doc, **session_options)

    application = Application(FunctionHandler(handler))
    kwargs = dict(port=port, prefix=prefix)
    if address is not None:
        kwargs["address"] = address
    if allow_websocket_origin:
        kwargs["allow_websocket_origin"] = list(allow_websocket_origin)
    return Server({"/": application}, **kwargs)


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
