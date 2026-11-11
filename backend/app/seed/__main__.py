"""`python -m app.seed` — wipe and load the deterministic demo data set, then train models and run the
AI pipeline once so dashboards are populated on first login (spec section 11)."""

import sys
import time

from app.db.session import SessionLocal
from app.seed.generator import generate
from app.seed.post import after_seed


def main() -> int:
    t0 = time.perf_counter()
    print("Seeding SmartStock demo data (this replaces all existing data)...")
    with SessionLocal() as db:
        info = generate(db)
        print(f"  data generated in {info['seconds']}s ({info['from']} to {info['to']})")
        after_seed(db, print)
    print(f"Done in {time.perf_counter() - t0:.1f}s. Logins: admin@demo.in / Admin@123, manager@demo.in / Manager@123, "
          "staff@demo.in / Staff@123, supplier1@demo.in / Supplier@123")
    return 0


if __name__ == "__main__":
    sys.exit(main())
