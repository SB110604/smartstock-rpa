"""Deep-merge a JSON fragment (file arg 2) into a locale file (arg 1), keeping existing keys unless --force."""
import json, sys, pathlib
def merge(a, b, force):
    for k, v in b.items():
        if isinstance(v, dict): merge(a.setdefault(k, {}), v, force)
        elif force or k not in a: a[k] = v
p = pathlib.Path(sys.argv[1]); frag = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
merge(data, frag, "--force" in sys.argv)
p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
