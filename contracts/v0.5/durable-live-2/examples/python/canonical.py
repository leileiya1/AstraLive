"""Normative Python hash-vector runner; shares the frozen canonical rules."""
import json
from pathlib import Path
import importlib.util
import sys
root=Path(__file__).resolve().parents[5]
spec=importlib.util.spec_from_file_location('answer_contract',root/'scripts/validate-answer-contract.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
if __name__=='__main__':
    if sys.argv[1]=='--lifecycle':
        trace=c.parse(Path(sys.argv[2]).read_text())
        print(json.dumps(c.validate_lifecycle_trace(trace),sort_keys=True))
        raise SystemExit(0)
    rows=c.parse(Path(sys.argv[1]).read_text())
    for row in rows:
        assert c.canonical(row['value']).decode()==row['canonicalUtf8']
        assert c.digest(row['value'])==row['sha256']
    print(json.dumps({r['name']:c.digest(r['value']) for r in rows},sort_keys=True))
