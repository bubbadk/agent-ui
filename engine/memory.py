"""Minimal episodic memory: goals + outcomes, retrieved by word overlap."""
import json
import os
import re
import threading
import time


class Memory:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.episodes = []
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                try:
                    self.episodes = json.load(f)
                except ValueError:
                    self.episodes = []

    def add(self, goal, outcome):
        with self.lock:
            self.episodes.append({
                't': time.strftime('%Y-%m-%d %H:%M'),
                'goal': goal,
                'outcome': (outcome or '')[:300],
            })
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.episodes[-500:], f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)

    def retrieve(self, query, k=3):
        words = set(re.findall(r'[a-zæøå]{3,}', query.lower()))
        scored = []
        for ep in self.episodes:
            ew = set(re.findall(r'[a-zæøå]{3,}', ep['goal'].lower()))
            overlap = len(words & ew)
            if overlap:
                scored.append((overlap, ep))
        scored.sort(key=lambda x: -x[0])
        if not scored:
            return ''
        lines = ['- %s (goal: %s)' % (ep['outcome'][:120], ep['goal'][:80])
                 for _, ep in scored[:k]]
        return '\n'.join(lines)
