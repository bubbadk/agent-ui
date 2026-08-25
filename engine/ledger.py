"""Append-only operation ledger — every agent action is posted here."""
import json
import os
import threading
import time


class Ledger:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.n = 0
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            e = json.loads(line)
                            self.n = max(self.n, e.get('id', 0))
                        except ValueError:
                            pass

    def append(self, kind, model='', tokens=None, detail=None):
        with self.lock:
            self.n += 1
            e = {
                'id': self.n,
                't': time.strftime('%H:%M:%S'),
                'kind': kind,
                'model': model,
                'detail': detail or {},
            }
            if tokens:
                e['tokens'] = {'in': tokens.get('in', 0), 'out': tokens.get('out', 0)}
                e['cost'] = round((tokens.get('in', 0) * 0.15 +
                                   tokens.get('out', 0) * 0.60) / 1e6, 6)
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(e, ensure_ascii=False) + '\n')
            return e

    def _entries(self):
        out = []
        if not os.path.exists(self.path):
            return out
        with open(self.path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
        return out

    def tail(self, n=60):
        return self._entries()[-n:]

    def since(self, entry_id):
        return [e for e in self._entries() if e.get('id', 0) > entry_id]

    def spent(self):
        return round(sum(e.get('cost', 0) for e in self._entries()), 4)
