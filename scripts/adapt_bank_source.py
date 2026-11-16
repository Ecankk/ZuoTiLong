"""Convert a pinned upstream source to standard JSONL; never open a database."""
import argparse
import importlib
import pkgutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.bank.source_records import canonical, validate
from scripts import bank_source_adapters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    adapters={m.name.replace('_','-'):m.name for m in pkgutil.iter_modules(bank_source_adapters.__path__) if not m.name.startswith('_')}
    parser.add_argument('--adapter', choices=sorted(adapters), required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exam-year', type=int)
    parser.add_argument('--math-type', type=int, choices=(1, 2, 3))
    parser.add_argument('--parts',nargs='+',choices=('strengthening','comprehensive','basic','lilin-880','wuzhongxiang-yanxuan','cxy-1k'),help='S03/S02 source parts')
    args = parser.parse_args()
    adapter=importlib.import_module('scripts.bank_source_adapters.'+adapters[args.adapter])
    if args.parts is not None and args.adapter not in ('zhangyu-html','cxy-daguan'):parser.error('--parts is only supported by zhangyu-html or cxy-daguan')
    batch = adapter.adapt(args.root, year=args.exam_year, math_type=args.math_type,**({'parts':args.parts} if args.parts is not None else {}))
    for record in batch:
        validate(record, args.root)
    with args.output.open('x', encoding='utf8', newline='\n') as output:
        for record in batch:
            output.write(canonical(record) + '\n')
    print(canonical(dict(schema='mathlens.bank-record/v1', records=len(batch), output=str(args.output))))


if __name__ == '__main__':
    main()
