"""Chargement du syllabus et utilitaires sur le graphe de prerequis."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, Iterable, List, Optional

from . import curriculum, syllabus_extra


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
    custom: bool = False
    pack: str = ""
    dependents: List[str] = field(default_factory=list)
    depth: int = 0


@dataclass
class Domain:
    id: str
    name: str
    description: str
    color: str
    custom: bool = False
    pack: str = ""


@dataclass
class Track:
    id: str
    title: str
    goal: str
    extra: List[str]
    group: str = curriculum.CUSTOM_GROUP
    custom: bool = False
    # liste explicite et ordonnee : le parcours n'est alors pas etendu aux
    # prerequis (parcours express, qui suppose le reste connu)
    courses: List[str] = field(default_factory=list)
    featured: bool = False


@dataclass
class TrackGroup:
    id: str
    name: str
    description: str
    pack: str = ""


@dataclass
class Pack:
    """Un morceau de syllabus : sa discipline et ce qu'il vise orientent la
    génération (voir curriculum.py)."""
    id: str
    title: str
    description: str = ""
    discipline: str = ""
    requires: List[str] = field(default_factory=list)
    goal: str = ""
    style: List[str] = field(default_factory=list)
    builtin: bool = False


class Syllabus:
    def __init__(self, data: dict):
        self.domains: Dict[str, Domain] = {
            d["id"]: Domain(**d) for d in data["domains"]
        }
        self.domain_order: List[str] = [d["id"] for d in data["domains"]]
        self.levels: Dict[int, str] = {
            l["value"]: l["name"] for l in (data.get("levels") or curriculum.DEFAULT_LEVELS)}
        self.packs: Dict[str, Pack] = {}
        for p in data.get("packs", []):
            self.packs[p["id"]] = Pack(**{k: p[k] for k in Pack.__dataclass_fields__ if k in p})
        self.courses: Dict[str, Course] = {}
        for c in data["courses"]:
            if c["id"] in self.courses:
                continue
            self.courses[c["id"]] = Course(
                id=c["id"], title=c["title"], domain=c["domain"], level=c["level"],
                prereqs=list(c["prereqs"]), summary=c["summary"],
                objectives=list(c["objectives"]), keywords=list(c["keywords"]),
                custom=bool(c.get("custom")), pack=c.get("pack", ""),
            )
        # un prerequis peut appartenir a un pack desactive : on l'ignore plutot
        # que de refuser tout le syllabus
        for course in self.courses.values():
            course.prereqs = [p for p in course.prereqs
                              if p in self.courses and p != course.id]
        self.order: List[str] = list(self.courses)
        self.track_groups: Dict[str, TrackGroup] = {
            g["id"]: TrackGroup(id=g["id"], name=g["name"], description=g.get("description", ""),
                                pack=g.get("pack", ""))
            for g in data.get("track_groups", [])
        }
        self.tracks: Dict[str, Track] = {}
        for t in data.get("tracks", []):
            courses = [c for c in t.get("courses", []) if c in self.courses]
            goal = t.get("goal") or (courses[-1] if courses else "")
            if goal not in self.courses:
                continue
            group = t.get("group") or curriculum.CUSTOM_GROUP
            if group not in self.track_groups:
                group = curriculum.CUSTOM_GROUP
                self.track_groups.setdefault(group, TrackGroup(
                    id=group, name="Mes parcours",
                    description="Les parcours que vous avez créés."))
            self.tracks[t["id"]] = Track(
                id=t["id"], title=t["title"], goal=goal,
                extra=[e for e in t.get("extra", []) if e in self.courses and e != goal],
                group=group, custom=bool(t.get("custom")), courses=courses,
                featured=bool(t.get("featured")))
        for cid, course in self.courses.items():
            for p in course.prereqs:
                self.courses[p].dependents.append(cid)
        self._compute_depth()
        # `order` suit la presentation du syllabus, qui n'est pas topologique :
        # un cours de probabilites peut dependre d'un cours de Fourier liste
        # plus loin. `topo` garantit qu'un prerequis vient toujours avant.
        self.topo: List[str] = sorted(
            self.order, key=lambda cid: (self.courses[cid].depth, self.order.index(cid)))
        self._topo_rank = {cid: i for i, cid in enumerate(self.topo)}

    def topo_rank(self, cid: str) -> int:
        return self._topo_rank.get(cid, 0)

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

    def pack_of(self, cid: str) -> Optional[Pack]:
        """Le pack qui oriente la génération du cours. Pour un cours ajouté à la
        main (pack « perso »), celui de son domaine s'il en a un."""
        c = self.courses.get(cid)
        if not c:
            return None
        pack = self.packs.get(c.pack)
        if pack is None or not pack.discipline:
            dom = self.domains.get(c.domain)
            owner = self.packs.get(dom.pack) if dom else None
            if owner is not None:
                return owner
        return pack

    def discipline(self, cid: Optional[str] = None) -> str:
        """Discipline d'un cours ; sans cours, celles du cursus actif."""
        if cid and cid in self.courses:
            pack = self.pack_of(cid)
            if pack and pack.discipline:
                return pack.discipline
        names = self.disciplines()
        if not names:
            return "sciences"
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " et " + names[-1]

    def disciplines(self) -> List[str]:
        out: List[str] = []
        for p in self.packs.values():
            if p.discipline and p.discipline not in out:
                out.append(p.discipline)
        return out

    def goals(self) -> List[str]:
        """Ce que visent les packs actifs, socle exclu."""
        return [p.goal for p in self.packs.values() if p.goal]

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

    def tracks_in(self, group_id: str) -> List[Track]:
        """Les parcours du groupe, ceux mis en avant d'abord."""
        tracks = [t for t in self.tracks.values() if t.group == group_id]
        return sorted(tracks, key=lambda t: not t.featured)

    def ordered_groups(self) -> List[str]:
        """Groupes de parcours, du pack le plus spécialisé au socle ; ceux de
        l'utilisateur en dernier. Les groupes vides sont omis."""
        rank = {pid: i for i, pid in enumerate(self.packs)}
        ids = [g for g in self.track_groups if self.tracks_in(g)]
        return sorted(ids, key=lambda g: (
            g == curriculum.CUSTOM_GROUP,
            -rank.get(self.track_groups[g].pack, -1),
            list(self.track_groups).index(g)))

    def group_name(self, group_id: str) -> str:
        g = self.track_groups.get(group_id)
        return g.name if g else group_id

    def _ordered(self, ids: List[str]) -> List[str]:
        """Liste choisie à la main (parcours express) : on garde son ordre, en
        faisant seulement passer avant un cours les prérequis, directs ou non,
        qui figurent aussi dans la liste. Les prérequis absents restent absents."""
        remaining = list(dict.fromkeys(ids))
        inside = set(remaining)
        needs = {cid: set(self.ancestors(cid)) & inside for cid in remaining}
        placed: List[str] = []
        done: set = set()
        while remaining:
            for cid in remaining:
                if needs[cid] <= done:
                    placed.append(cid)
                    done.add(cid)
                    remaining.remove(cid)
                    break
            else:               # impossible : le graphe est acyclique
                placed.extend(remaining)
                break
        return placed

    def track_path(self, track_id: str) -> List[str]:
        track = self.tracks[track_id]
        if track.courses:
            return self._ordered(track.courses)
        targets = [track.goal] + track.extra
        seen: List[str] = []
        for t in targets:
            for cid in self.path_to(t):
                if cid not in seen:
                    seen.append(cid)
        return seen


@lru_cache(maxsize=1)
def load() -> Syllabus:
    """Syllabus de base, augmenté des ajouts faits depuis l'application."""
    return Syllabus(syllabus_extra.merged())


def reload() -> Syllabus:
    """À appeler après avoir modifié les ajouts de l'utilisateur."""
    load.cache_clear()
    return load()
