"""Regenerate docs/API.md from the FastAPI route table: `python scripts/gen_api_docs.py`."""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.routing import APIRoute

from app.main import app

INTRO = """# SmartStock RPA — API summary

Generated from the code by `python scripts/gen_api_docs.py`. The full interactive reference (schemas, try-it-out) is
FastAPI's OpenAPI UI at **http://localhost:8000/docs**.

**Conventions**
- Base path `/api/v1`, JSON. Auth: `Authorization: Bearer <access token>` from `POST /auth/login`; refresh with
  `POST /auth/refresh`. The POS endpoint uses `X-API-Key`; one-click approval endpoints use the token in the URL.
- Lists accept `page`, `page_size` (≤ 500) and `sort` (`field` / `-field`) and return `{items, total, page, page_size}`.
- Errors: `{"detail": "...", "code": "..."}` (validation errors add `errors: [{field, message}]`). Invalid workflow
  transitions return **409** `invalid_transition`; missing permission **403** `forbidden`; login rate limit **429**.
- Permission names come from `app/core/permissions.py` (role matrix in the README).
"""


def permission(route: APIRoute) -> str:
    names = [d.call.__name__ for d in route.dependant.dependencies if hasattr(d.call, "__name__")]
    for n in names:
        if n.startswith("require_") and n != "require_supplier":
            return n[len("require_"):].replace("_", ".", 1)
    if "get_current_user" in names:
        return "any logged-in user"
    return "public"


def main() -> None:
    groups: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        doc = (r.endpoint.__doc__ or r.name.replace("_", " ")).strip().splitlines()[0]
        for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
            groups[(r.tags or ["other"])[0]].append((m, r.path, permission(r), doc))
    out = [INTRO]
    for tag in sorted(groups):
        out += [f"\n## {tag.title()}\n", "| Method | Path | Permission | Purpose |", "|---|---|---|---|"]
        out += [f"| {m} | `{p}` | {perm} | {d} |" for m, p, perm, d in sorted(groups[tag], key=lambda x: (x[1], x[0]))]
    target = Path(__file__).resolve().parents[2] / "docs" / "API.md"
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {target} ({sum(len(v) for v in groups.values())} endpoints)")


if __name__ == "__main__":
    main()
