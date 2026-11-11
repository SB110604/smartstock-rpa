"""List i18n keys used in frontend/src that are missing from a locale file.
Usage: python scripts/i18n-keys.py [en|hi|mr]"""
import json, re, sys, pathlib
root = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src"
lang = sys.argv[1] if len(sys.argv) > 1 else "en"
data = json.loads((root / "i18n" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
def flat(d, p=""):
    for k, v in d.items():
        if isinstance(v, dict): yield from flat(v, p + k + ".")
        else: yield p + k
have = set(flat(data))
used = set()
for f in root.rglob("*.tsx"):
    used |= set(re.findall(r"\bt\(\s*['`]([a-zA-Z][\w.]*)['`]", f.read_text(encoding="utf-8")))
for f in root.rglob("*.ts"):
    used |= set(re.findall(r"\bt\(\s*['`]([a-zA-Z][\w.]*)['`]", f.read_text(encoding="utf-8")))
missing = sorted(k for k in used if k not in have and not k.endswith("."))
print("\n".join(missing)); print(f"# {len(missing)} missing of {len(used)} used", file=sys.stderr)
