#!/usr/bin/env python3
"""Генератор глобального реестра block-state id из misode/mcmeta summary.

Vanilla назначает state id: блоки по алфавиту, внутри блока — комбинации
свойств в порядке объявления (последнее свойство меняется быстрее всего).
Выход: tools/mc_states_registry.json: {name: [first_id, last_id]}
"""
import json, itertools, os, sys, urllib.request

SUMMARY_URL = 'https://raw.githubusercontent.com/misode/mcmeta/summary/blocks/data.json'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mc_states_registry.json')

def build(version='1.21.1'):
    url = f'https://raw.githubusercontent.com/misode/mcmeta/{version}-summary/blocks/data.json'
    with urllib.request.urlopen(url) as r:
        data = json.load(r)
    reg = {}
    nid = 0
    for name in sorted(data.keys()):
        props = data[name][0] or {}
        keys = list(props.keys())
        combos = 1
        for k in keys: combos *= len(props[k])
        reg[name] = [nid, nid + combos - 1]
        nid += combos
    json.dump(reg, open(OUT, 'w'))
    print('блоков:', len(reg), 'max id:', nid - 1, '->', OUT)

def name_for(state_id, reg):
    # бинарный поиск по диапазонам
    names = sorted(reg.keys())
    lo, hi = 0, len(names) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        f, l = reg[names[mid]]
        if state_id < f: hi = mid - 1
        elif state_id > l: lo = mid + 1
        else: return names[mid]
    return None

if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else '1.21.1')
