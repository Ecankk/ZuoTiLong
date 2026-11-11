"""Local Uvicorn launcher. The application owns its resources via lifespan."""
import argparse
from contextlib import asynccontextmanager
import os
import sys

import uvicorn

from app.config import AppConfig
from app.hosting import bind_socket, clear_address, publish_address
from app.main import create_app


class Parser(argparse.ArgumentParser):
    def error(self,message):
        if '--desktop' in sys.argv or '--prepare-desktop' in sys.argv:
            from app.desktop.protocol import Protocol
            Protocol('prepare' if '--prepare-desktop' in sys.argv else 'serve',None).emit('error',status='failed',error=dict(code='invalid_arguments',message=message,retryable=False))
            raise SystemExit(2)
        super().error(message)


def main():
    if '--desktop' in sys.argv or '--prepare-desktop' in sys.argv:
        for stream in (sys.stdin,sys.stdout,sys.stderr):
            if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf8',errors='replace')
    parser = Parser(description='MathLens local paper review')
    parser.add_argument('--host', default='127.0.0.1', choices=['127.0.0.1', 'localhost', '::1'])
    parser.add_argument('--port', type=int)
    parser.add_argument('--auto-port', action='store_true')
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--desktop',action='store_true');mode.add_argument('--prepare-desktop',action='store_true')
    for name in ('resource-root','data-dir','library-dir','dist-dir','launch-nonce'):parser.add_argument('--'+name)
    args = parser.parse_args()
    if args.desktop or args.prepare_desktop:return desktop(args)
    if args.data_dir or args.library_dir or args.dist_dir or args.launch_nonce:parser.error('桌面路径参数需要--desktop或--prepare-desktop')
    args.port=4173 if args.port is None else args.port
    config = AppConfig.from_env(args.resource_root)
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


def desktop(args):
    import errno,logging,re,sqlite3
    from app.desktop.protocol import Protocol,DesktopError,Cancelled
    from app.desktop.control import ParentControl,CANCEL,checkpoint
    from app.desktop.config import settings
    protocol=Protocol('prepare' if args.prepare_desktop else 'serve',args.launch_nonce if re.fullmatch('[0-9a-f]{64}',args.launch_nonce or '') else None)
    control=ParentControl(sys.stdin,args.launch_nonce);protocol.on_disconnect=control.request_stop;control.start();token=CANCEL.set(control.stop)
    try:
        protocol.progress('validate_config','正在检查数据位置');checkpoint()
        config=settings(args)
        if args.prepare_desktop:
            from app.desktop.prepare import prepare
            prepare(config,protocol);return 0
        if args.host!='127.0.0.1' or args.port not in (None,0) or args.auto_port:raise DesktopError('invalid_arguments','桌面服务必须使用127.0.0.1和端口0',2)
        from app.desktop.prepare import check_workspace
        check_workspace(config)
        if not config.library_database.is_file() or not config.database.is_file() or not (config.data/'workspace.json').is_file():raise DesktopError('workspace_incomplete','请先准备桌面题库和工作区',12)
        return desktop_server(config,protocol,control)
    except Cancelled as exc:
        if args.prepare_desktop:protocol.emit('error',status='cancelled',error=dict(code='cancelled',message='已取消准备',retryable=True),library_published=getattr(exc,'library_published',False),workspace_ready=False)
        else:
            protocol.phase='stopped';protocol.emit('stopped',status='completed')
        return 130 if args.prepare_desktop else 0
    except (Exception,SystemExit) as exc:
        if isinstance(exc,DesktopError):code,exit_code=exc.code,exc.exit_code
        elif isinstance(exc,sqlite3.Error) and getattr(exc,'sqlite_errorcode',None) in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):code,exit_code='library_busy',13
        elif isinstance(exc,sqlite3.Error) and getattr(exc,'sqlite_errorcode',None) in (sqlite3.SQLITE_FULL,sqlite3.SQLITE_READONLY,sqlite3.SQLITE_CANTOPEN):code,exit_code=('disk_full' if exc.sqlite_errorcode==sqlite3.SQLITE_FULL else 'permission_denied'),10
        elif isinstance(exc,OSError):
            code,exit_code=('disk_full' if exc.errno==errno.ENOSPC else 'permission_denied'),10
        else:code,exit_code='initialization_failed',20
        logging.exception('Desktop operation failed')
        protocol.emit('error',status='failed',error=dict(code=code,message=str(exc)[:500],retryable=exit_code in (10,13,20)),library_published=getattr(exc,'library_published',False),workspace_ready=getattr(exc,'workspace_ready',False))
        return exit_code
    finally:CANCEL.reset(token)


def desktop_server(config,protocol,control):
    from app.desktop.control import checkpoint
    from app.desktop.protocol import Cancelled
    checkpoint();sock,_=bind_socket('127.0.0.1',0);app=None;startup_error=[]
    try:
        app=create_app(config,startup_progress=protocol.progress,cancel_event=control.stop,launch_nonce=protocol.nonce)
        original=app.router.lifespan_context
        @asynccontextmanager
        async def lifespan(application):
            try:
                async with original(application):
                    checkpoint();address=publish_address(config.data,sock,protocol.nonce)
                    protocol.phase='address_published';protocol.emit('address_published',status='completed',server=address)
                    yield
                    protocol.progress('stopping','正在关闭本地服务')
            except BaseException as exc:
                startup_error.append(exc);raise
        app.router.lifespan_context=lifespan
        server=uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False,timeout_graceful_shutdown=5))
        control.on_stop=lambda:setattr(server,'should_exit',True)
        if control.stop.is_set():raise Cancelled('已取消')
        try:server.run(sockets=[sock])
        except SystemExit:
            if startup_error:raise startup_error[-1]
            raise
        if startup_error:raise startup_error[-1]
    finally:
        # The factory may fail before Uvicorn enters lifespan.
        try:
            if app is not None:app.state.runtime.close()
        finally:
            sock.close();clear_address(config.data,os.getpid(),protocol.nonce)
    protocol.phase='stopped';protocol.emit('stopped',status='completed');return 0
