"""Local Uvicorn launcher. The application owns its resources via lifespan."""
import argparse
from contextlib import asynccontextmanager
import os

import uvicorn

from app.config import AppConfig
from app.hosting import bind_socket, clear_address, publish_address
from app.main import create_app


def main():
    parser = argparse.ArgumentParser(description='MathLens local paper review')
    parser.add_argument('--host', default='127.0.0.1', choices=['127.0.0.1', 'localhost', '::1'])
    parser.add_argument('--port', type=int, default=4173)
    parser.add_argument('--auto-port', action='store_true')
    args = parser.parse_args()
    config = AppConfig.from_env()
    legacy = config.root / '.mathlens'
    if not os.environ.get('MATHLENS_DATA_DIR') and not config.database.exists() and (legacy/'mathlens.db').is_file():
        from app.storage.split import migrate_legacy
        moved = migrate_legacy(legacy,config)
        print(f"Migrated library and workspace; original data retained at {moved['legacy_preserved']}",flush=True)
    try:
        sock, failures = bind_socket(args.host, args.port, args.auto_port)
    except RuntimeError as exc:
        parser.exit(1, f'MathLens: {exc}\n')
    app = create_app(config)
    # Publish only after initialization succeeds. Health still gates browser
    # opening, and the finally block removes only this process's address.
    original_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            address = publish_address(config.data, sock)
            for failure in failures:
                print(f"Port {failure['port']} unavailable (error {failure['code']}); selected another local port.")
            print(f"MathLens running at {address['url']}", flush=True)
            print(f'Data directory: {config.data}', flush=True)
            yield
    app.router.lifespan_context = lifespan
    try:
        server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False))
        server.run(sockets=[sock])
    finally:
        sock.close()
        clear_address(config.data, os.getpid())
