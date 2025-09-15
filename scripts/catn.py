import sys

path = sys.argv[1]
with open(path, 'r', encoding='utf-8', errors='ignore') as f:
    for i, line in enumerate(f, start=1):
        print(f"{i:04d}: {line}", end='')
