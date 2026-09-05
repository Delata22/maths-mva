"""Chargement du syllabus et utilitaires sur le graphe de prerequis."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, Iterable, List, Optional

from .paths import SYLLABUS_FILE


@dataclass
class Course:
    id: str
    title: str
    domain: str
    level: int
    prereqs: List[str]
    summary: str
    objectives: List[str]
    keywords: List[str]
    dependents: List[str] = field(default_factory=list)
    depth: int = 0


@dataclass
class Domain:
    id: str
    name: str
    description: str
    color: str


@dataclass
class Track:
    id: str
    title: str
    goal: str
    extra: List[str]


class Syllabus:
    def __init__(self, data: dict):
        self.domains: Dict[str, Domain] = {
            d["id"]: Domain(**d) for d in data["domains"]
        }
        self.domain_order: List[str] = [d["id"] for d in data["domains"]]
        self.levels: Dict[int, str] = {l["value"]: l["name"] for l in data["levels"]}
        self.courses: Dict[str, Course] = {}
        for c in data["courses"]:
            self.courses[c["id"]] = Course(
                id=c["id"], title=c["title"], domain=c["domain"], level=c["level"],
                prereqs=list(c["prereqs"]), summary=c["summary"],
                objectives=list(c["objectives"]), keywords=list(c["keywords"]),
            )
        self.order: List[str] = [c["id"] for c in data["courses"]]
        self.tracks: Dict[str, Track] = {
            t["id"]: Track(id=t["id"], title=t["title"], goal=t["goal"], extra=list(t["extra"]))
            for t in data.get("tracks", [])
        }
        for cid, course in self.courses.items():
            for p in course.prereqs:
                self.courses[p].dependents.append(cid)
        self._compute_depth()

    def _compute_depth(self) -> None:
        memo: Dict[str, int] = {}

        def depth(cid: str) -> int:
            if cid in memo:
                return memo[cid]
            course = self.courses[cid]
            memo[cid] = 0 if not course.prereqs else 1 + max(depth(p) for p in course.prereqs)
            return memo[cid]

        for cid in self.courses:
            self.courses[cid].depth = depth(cid)

    # ------------------------------------------------------------------ acces
    def get(self, cid: str) -> Optional[Course]:
        return self.courses.get(cid)

    def title(self, cid: str) -> str:
        c = self.courses.get(cid)
        return c.title if c else cid

    def domain_name(self, did: str) -> str:
        d = self.domains.get(did)
        return d.name if d else did

    def domain_color(self, did: str) -> str:
        d = self.domains.get(did)
        return d.color if d else "#94a3b8"

    def all(self) -> List[Course]:
        return [self.courses[cid] for cid in self.order]

    def by_domain(self, did: str) -> List[Course]:
        return [c for c in self.all() if c.domain == did]

    # ------------------------------------------------------------- parcours
    def ancestors(self, cid: str) -> List[str]:
        """Tous les prerequis, directs et indirects, en ordre topologique."""
        seen: List[str] = []
        visited = set()

        def walk(node: str) -> None:
            for p in self.courses[node].prereqs:
                if p not in visited:
                    visited.add(p)
                    walk(p)
                    seen.append(p)

        walk(cid)
        return seen

    def descendants(self, cid: str) -> List[str]:
        out: List[str] = []
        visited = set()
        stack = list(self.courses[cid].dependents)
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            out.append(n)
            stack.extend(self.courses[n].dependents)
        return out

    def path_to(self, cid: str) -> List[str]:
        """Ordre d'etude recommande pour atteindre `cid` (prerequis inclus)."""
        return self.ancestors(cid) + [cid]

    def track_path(self, track_id: str) -> List[str]:
        track = self.tracks[track_id]
        targets = [track.goal] + track.extra
        seen: List[str] = []
        for t in targets:
            for cid in self.path_to(t):
                if cid not in seen:
                    seen.append(cid)
        return seen


@lru_cache(maxsize=1)
def load() -> Syllabus:
    with open(SYLLABUS_FILE, "r", encoding="utf-8") as fh:
        return Syllabus(json.load(fh))
