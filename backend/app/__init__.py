import os

# joblib/loky probes physical cores via `wmic`, which is missing on recent Windows; give it a value up front.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 2))
