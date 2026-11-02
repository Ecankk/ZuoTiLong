"""Measure saved workspace reads; point both paths at an isolated data copy."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import AppConfig
from app.storage.database import Database
from app.services import workspace
from starlette.responses import JSONResponse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=7)
    parser.add_argument('--save', type=Path)
    parser.add_argument('--http', action='store_true', help='also measure the ASGI endpoint, without starting jobs or migrations')
    parser.add_argument('--uncached', action='store_true', help='use the original uncached read model as a baseline')
    args = parser.parse_args()
    config = AppConfig.from_env()
    service = workspace.WorkspaceService(config, Database(config))
    samples = []
    parts = {}

    def timed(name, fn):
        def call(*a, **kw):
            start = perf_counter()
            try:
                return fn(*a, **kw)
            finally:
                parts[name] = parts.get(name, 0) + (perf_counter() - start) * 1000
        return call

    original_rows = workspace.rows
    def measured_rows(conn, sql, *a):
        name = 'papers' if sql.startswith('SELECT * FROM papers ORDER') else 'questions' if sql.startswith('SELECT * FROM questions ORDER') else 'other_rows'
        return timed(name, original_rows)(conn, sql, *a)

    try:
        with ExitStack() as stack:
            if args.uncached:
                stack.enter_context(patch.object(service, 'bootstrap', service._build_bootstrap))
            for name, fn in [('bank', 'public_bank'), ('profile', 'build_profile'), ('loop', 'loop_snapshot'), ('preferences', 'preferences')]:
                stack.enter_context(patch.object(workspace, fn, timed(name, getattr(workspace, fn))))
            stack.enter_context(patch.object(workspace, 'rows', measured_rows))
            for _ in range(args.runs):
                parts.clear()
                start = perf_counter()
                value = service.bootstrap()
                read_ms = (perf_counter() - start) * 1000
                start = perf_counter()
                body = JSONResponse(value).body
                samples.append(dict(read_ms=read_ms, json_ms=(perf_counter()-start)*1000, bytes=len(body), parts_ms=dict(parts)))
            http_samples = []
            if args.http:
                from fastapi.testclient import TestClient
                from app.main import create_app
                app = create_app(config, agent_factory=None)
                app.state.runtime.workspace = service
                # No context manager: deliberately skip application startup,
                # schema migrations and workflow/Agent lifecycle on saved data.
                client = TestClient(app, base_url='http://127.0.0.1')
                try:
                    for _ in range(args.runs):
                        start = perf_counter()
                        response = client.get('/api/bootstrap')
                        response.raise_for_status()
                        http_samples.append((perf_counter()-start)*1000)
                        assert response.content == body
                finally:
                    client.close()
        if args.save:
            args.save.write_bytes(body)
        print(json.dumps({'counts': {k: len(value[k]) for k in ('papers', 'questions', 'bank')},
                          'samples': samples, 'median_read_ms': statistics.median(s['read_ms'] for s in samples),
                          'median_total_ms': statistics.median(s['read_ms']+s['json_ms'] for s in samples),
                          'http_ms': http_samples,
                          'median_http_ms': statistics.median(http_samples) if http_samples else None}, indent=2))
    finally:
        service.close()


if __name__ == '__main__':
    main()
