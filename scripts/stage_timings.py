"""Read-only timing summary of saved Agent turns, grouped by task_kind.

created_to_finished includes queueing and repairs; started_to_finished is the
latest dispatch interval, not cumulative model time across retries. Missing
historical timestamps are counted, never inferred from updated_at.
"""
import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from statistics import median


def summarize(turns):
    groups = defaultdict(list)
    for turn in turns:
        if turn.get('task_kind'):
            groups[turn['task_kind']].append(turn)
    result = {}
    for kind, items in sorted(groups.items()):
        summary = {'turns': len(items), 'completed': sum(t.get('status') == 'completed' for t in items)}
        for label, field in [('created_to_finished', 'created_at'), ('started_to_finished', 'started_at')]:
            values = []
            invalid = 0
            for turn in items:
                if turn.get('status') != 'completed' or not turn.get(field) or not turn.get('finished_at'):
                    continue
                try:
                    seconds = (datetime.fromisoformat(turn['finished_at'])-datetime.fromisoformat(turn[field])).total_seconds()
                    if seconds < 0:
                        raise ValueError('negative duration')
                    values.append(seconds)
                except (ValueError, TypeError):
                    invalid += 1
            summary[label] = {'count': len(values), 'missing_or_invalid': summary['completed']-len(values),
                              'invalid': invalid, 'median_seconds': median(values) if values else None,
                              'max_seconds': max(values) if values else None}
        result[kind] = summary
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session_database', type=Path, help='agent-session.db in an isolated copy')
    args = parser.parse_args()
    with closing(sqlite3.connect(args.session_database.resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        row = conn.execute('SELECT payload FROM session WHERE id=1').fetchone()
    turns = json.loads(row[0]).get('turns', []) if row else []
    print(json.dumps({'source': 'saved session projection; completed turns only',
                      'unclassified_turns': sum(not t.get('task_kind') for t in turns),
                      'kinds': summarize(turns)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
