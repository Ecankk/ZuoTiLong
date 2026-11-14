"""Frozen sidecar entry; never relaunch sys.executable with -m app."""
from multiprocessing import freeze_support

if __name__=='__main__':
    freeze_support()
    # Smoke-only restriction; normal desktop launches do not set this switch.
    import os
    if os.environ.get('MATHLENS_PACKAGING_OFFLINE_SMOKE')=='1':
        import socket
        original=socket.socket.connect
        def offline_connect(sock,address):
            if isinstance(address,tuple) and address[0] in ('127.0.0.1','::1','localhost'):return original(sock,address)
            raise OSError('Frozen smoke: external Python socket connections disabled')
        socket.socket.connect=offline_connect
        import onnxruntime
        onnxruntime.disable_telemetry_events()
    from app.cli import main
    raise SystemExit(main())
