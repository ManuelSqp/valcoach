"""Walkable-area grid from the minimap image, for estimating routes between known positions.

The API only gives positions at kills, plants and defuses. Between two known
positions of a player we assume the shortest walkable route (the map image's
opaque area = floor). That's an estimate, not tracking: the replay draws these
segments faded so it's clear what is known and what is guessed.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
from scipy import ndimage

GRID = 192            # cells per side; ~5 m per cell on a typical map


class NavGrid:
    def __init__(self, walkable: np.ndarray):
        self.walk = walkable.astype(bool)
        self.n = self.walk.shape[0]
        # nearest walkable cell for every cell (positions slightly off the floor get snapped)
        _, idx = ndimage.distance_transform_edt(~self.walk, return_indices=True)
        self.snap_r, self.snap_c = idx[0], idx[1]
        self._cache: dict[tuple, list] = {}

    # ------------------------------------------------------------------
    @classmethod
    def from_image(cls, path: str | Path | None, grid: int = GRID) -> "NavGrid | None":
        if not path or not Path(path).exists():
            return None
        import cv2   # imported here so a broken OpenCV install can't break jobs without a map image
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
        if img.ndim == 3 and img.shape[2] == 4:
            floor = img[:, :, 3] > 40                       # transparent background
        else:
            gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            floor = gray > 40                                # dark background
        small = cv2.resize(floor.astype(np.float32), (grid, grid), interpolation=cv2.INTER_AREA) > 0.35
        small = ndimage.binary_dilation(small, iterations=1)  # keep 1-cell corridors connected
        if small.mean() < 0.05 or small.mean() > 0.98:
            return None                                       # not a usable floor plan
        return cls(small)

    def cell(self, u: float, v: float) -> tuple[int, int]:
        c = min(self.n - 1, max(0, int(u * self.n)))
        r = min(self.n - 1, max(0, int(v * self.n)))
        return int(self.snap_r[r, c]), int(self.snap_c[r, c])

    def route(self, a: tuple[float, float], b: tuple[float, float]) -> list[tuple[float, float]]:
        """Walkable route from a to b in map UV (0..1), simplified; includes both end points."""
        ca, cb = self.cell(*a), self.cell(*b)
        key = (ca, cb)
        if key not in self._cache:
            self._cache[key] = self._bfs(ca, cb)
        mid = self._cache[key]
        return [tuple(a)] + mid + [tuple(b)]

    def _bfs(self, s: tuple[int, int], t: tuple[int, int]) -> list[tuple[float, float]]:
        if s == t:
            return []
        n, walk = self.n, self.walk
        parent = np.full(n * n, -1, dtype=np.int32)
        start, goal = s[0] * n + s[1], t[0] * n + t[1]
        parent[start] = start
        q = deque([start])
        steps = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))
        found = False
        while q:
            cur = q.popleft()
            if cur == goal:
                found = True
                break
            r, c = divmod(cur, n)
            for dr, dc in steps:
                rr, cc = r + dr, c + dc
                if 0 <= rr < n and 0 <= cc < n and walk[rr, cc]:
                    nb = rr * n + cc
                    if parent[nb] < 0:
                        # no diagonal corner-cutting through walls
                        if dr and dc and not (walk[r, cc] and walk[rr, c]):
                            continue
                        parent[nb] = cur
                        q.append(nb)
        if not found:
            return []                        # not connected: straight line
        cells = []
        cur = goal
        while cur != start:
            cells.append(divmod(cur, n))
            cur = int(parent[cur])
        cells.append(divmod(start, n))
        cells.reverse()
        pts = np.array([[c + 0.5, r + 0.5] for r, c in cells], dtype=np.float64)
        simple = _simplify(pts, 1.2)
        inner = simple[1:-1] if len(simple) > 2 else simple[0:0]
        return [(float(x) / n, float(y) / n) for x, y in inner]


def _simplify(pts: np.ndarray, eps: float) -> np.ndarray:
    """Ramer-Douglas-Peucker: drop points closer than eps to the line between kept points."""
    if len(pts) < 3:
        return pts
    keep = np.zeros(len(pts), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        a, b = pts[i], pts[j]
        ab = b - a
        seg = pts[i + 1:j] - a
        norm = np.hypot(*ab)
        if norm == 0:
            d = np.hypot(seg[:, 0], seg[:, 1])
        else:
            d = np.abs(ab[0] * seg[:, 1] - ab[1] * seg[:, 0]) / norm
        k = int(np.argmax(d))
        if d[k] > eps:
            m = i + 1 + k
            keep[m] = True
            stack += [(i, m), (m, j)]
    return pts[keep]


def path_length(pts: list[tuple[float, float]]) -> float:
    return float(sum(np.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])))
