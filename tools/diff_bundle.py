import json, difflib, os
b = json.load(open('_site_snapshot/engine_bundle.json', encoding='utf-8'))
for k, v in b.items():
    if not os.path.exists(k):
        print("MISSING locally:", k); continue
    cur = open(k, encoding='utf-8').read().replace('\r\n', '\n'); v = v.replace('\r\n', '\n')
    if cur != v:
        diff = list(difflib.unified_diff(v.splitlines(), cur.splitlines(), 'bundle/' + k, 'local/' + k, lineterm='', n=1))
        print(f"DIFFERS: {k} ({len(diff)} diff lines)"); print("\n".join(diff[:80]))
extra = []
for r, _, fs in os.walk('.'):
    for f in fs:
        p = os.path.join(r, f).replace(os.sep, '/')[2:]
        if p.split('/')[0] in ('engine', 'config', 'variants', 'variants_private') and p.endswith(('.py', '.json')) and p not in b:
            extra.append(p)
print("local engine/config/variant files not in bundle:", sorted(extra))
