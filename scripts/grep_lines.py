import sys
from pathlib import Path

pattern = sys.argv[1]
for path in sys.argv[2:]:
    p = Path(path)
    if not p.exists():
        continue
    with p.open('r', encoding='utf-8', errors='ignore') as f:
        for i, line in enumerate(f, start=1):
            if pattern in line:
                print(f"{path}:{i}")
