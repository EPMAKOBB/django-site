"""Independent solutions for the local FIPI demo files; no database writes."""
from collections import defaultdict
from decimal import Decimal
from heapq import heappop, heappush
from pathlib import Path
from math import dist
import re


def verify_adapted_2026_cluster(path):
    """Part B alone is a self-contained two-number problem, with anomalies."""
    points = [tuple(map(float, line.replace(",", ".").split()))
              for line in Path(path).read_text(encoding="utf-8-sig").splitlines()]
    partitions = []
    for epsilon in (1.0, 1.5):
        remaining = set(range(len(points)))
        groups = []
        while remaining:
            group = [remaining.pop()]
            queue = group.copy()
            while queue:
                index = queue.pop()
                neighbours = {j for j in remaining if dist(points[index], points[j]) < epsilon}
                remaining -= neighbours
                group.extend(neighbours)
                queue.extend(neighbours)
            groups.append(group)
        assert sorted(map(len, groups)) == [1, 1, 1, 100, 113, 407]
        partitions.append({frozenset(c) for c in groups})
    assert partitions[0] == partitions[1]
    clusters = sorted((c for c in groups if len(c) > 1), key=len)
    centers = []
    for cluster in clusters:
        scores = sorted((sum(dist(points[i], points[j]) for j in cluster), i) for i in cluster)
        assert scores[1][0] - scores[0][0] > 1e-7
        centers.append(scores[0][1])
    result = [int(dist(points[centers[0]], points[centers[-1]]) * 10000),
              int(max(dist(points[i], points[j]) for i, c in zip(centers, clusters) for j in c) * 10000)]
    assert result == [142058, 25299], result
    return result


def verify_content(files):
    files = Path(files)
    # Bottom-up evaluation avoids both recursion depth and exponential calls.
    q = {n: n + 4 for n in range(21)}
    for n in range(21, 11244):
        q[n] = q[n - 4] + 2
    g = {n: q[n] for n in range(11240, 11244)}
    for n in range(11239, 0, -1):
        g[n] = g[n + 3] + 2
    f = {n: g[n + 4] for n in range(1, 43)}
    for n in range(43, 2027):
        f[n] = 2 * f[n - 2] - f[n - 4] + 2
    assert f[2026] == 998154, f[2026]

    edges = defaultdict(list)
    for line in (files / "demo_23.txt").read_text(encoding="utf-8-sig").splitlines():
        a, b, w = line.split()
        edges[int(a)].append((int(b), Decimal(w.replace(",", "."))))
    distances, queue = {1: Decimal(0)}, [(Decimal(0), 1)]
    while queue:
        d, a = heappop(queue)
        if d != distances[a]:
            continue
        for b, w in edges[a]:
            candidate = d + w
            if candidate < distances.get(b, Decimal("Infinity")):
                distances[b] = candidate
                heappush(queue, (candidate, b))
    assert int(distances[100]) == 10971, distances[100]

    text = (files / "demo_24.txt").read_text(encoding="utf-8-sig").strip()
    assert set(text) <= set("06789-*")
    number = r"(?:[6789][06789]*|0)"
    longest = max(len(m[0]) for m in re.finditer(number + r"(?:[-*]" + number + r")*", text))
    # Independent linear state machine: longest valid suffix ending in a number.
    start = None
    zero_number = False
    previous_operator = False
    linear_longest = 0
    for i, char in enumerate(text):
        if char in "-*":
            if start is None or previous_operator:
                start = None
            previous_operator = True
            zero_number = False
        else:
            if start is None or zero_number:
                start = i
            if previous_operator or start == i:
                zero_number = char == "0"
            previous_operator = False
            linear_longest = max(linear_longest, i - start + 1)
    assert longest == linear_longest == 154, (longest, linear_longest)

    particles = []
    for line in (files / "demo_27.txt").read_text(encoding="utf-8-sig").splitlines():
        *values, kind = line.replace(",", ".").split()
        x, y, vx, vy, mass = map(Decimal, values)
        particles.append((mass * (vx * vx + vy * vy) / 2, x, y, kind))
    particles.sort()
    clusters = []
    for particle in particles:
        if not clusters or particle[0] - clusters[-1][0][0] > 2:
            clusters.append([])
        clusters[-1].append(particle)
    assert len(clusters) == 4
    # The supplied project file has even-sized clusters and TWO medoids each.
    # Its published key chooses the upper-energy medoid. Report the ambiguity;
    # do not pretend this verifies the uniqueness promised by the original text.
    ambiguous = [len(c) for c in clusters if len(c) % 2 == 0 and c[len(c)//2-1][0] != c[len(c)//2][0]]
    max_distance_squared = Decimal(0)
    for cluster in clusters:
        chosen = [(x, y) for _, x, y, kind in cluster if kind == "II"]
        for i, (x, y) in enumerate(chosen):
            for a, b in chosen[i + 1:]:
                max_distance_squared = max(max_distance_squared, (x-a)**2 + (y-b)**2)
    answer27 = [int(max_distance_squared.sqrt() * 10000),
                int(max(c[len(c)//2][0] for c in clusters) * 10000)]
    assert answer27 == [539936, 100704], answer27
    return {"recursion_1177": f[2026], "demo23": int(distances[100]), "demo24": longest,
            "demo27_upper_median": answer27, "cluster_sizes": [len(c) for c in clusters],
            "ambiguous_cluster_sizes": ambiguous,
            "demo27_lower_median_energy_answer": int(max(c[(len(c)-1)//2][0] for c in clusters) * 10000)}


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_content(args.files), ensure_ascii=False, indent=2))
