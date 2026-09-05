"""Chaine de generation d'un cours : plan -> sections -> exercices."""
from __future__ import annotations

import time
from typing import Callable, List, Optional

from .. import content, settings, store
from ..syllabus import Syllabus, load as load_syllabus
from . import claude_cli as cc
from . import prompts

ProgressCb = Callable[[str, float], None]
CancelCb = Callable[[], bool]


def _noop(_label: str, _frac: float) -> None:
    pass


def _never() -> bool:
    return False


class GenerationCancelled(RuntimeError):
    pass


def _check(cancel: CancelCb) -> None:
    if cancel():
        raise GenerationCancelled("Generation annulee.")


def generate_plan(syl: Syllabus, course_id: str, model: str,
                  on_progress: ProgressCb = _noop, cancel: CancelCb = _never) -> dict:
    course = syl.get(course_id)
    if course is None:
        raise ValueError("cours inconnu : %s" % course_id)
    on_progress("Plan du cours", 0.02)
    max_sections = int(settings.get("gen/max_sections") or 9)
    plan, res = cc.run_json(
        prompts.plan_prompt(syl, course, max_sections),
        model=model,
        system="Vous concevez des cours de mathematiques. Vous repondez uniquement en JSON valide.",
        schema=prompts.PLAN_SCHEMA,
        cancel=cancel,
    )
    sections = plan.get("sections") or []
    if not sections:
        raise cc.ClaudeError("Le plan renvoye ne contient aucune section.")
    plan.setdefault("proved_in_course", [])
    plan.setdefault("left_as_exercise", [])
    plan["_cost"] = res.cost_usd
    content.write_json(course_id, content.PLAN, plan)
    return plan


def generate_sections(syl: Syllabus, course_id: str, plan: dict, model: str,
                      on_progress: ProgressCb = _noop,
                      cancel: CancelCb = _never) -> tuple[str, float]:
    course = syl.get(course_id)
    sections: List[dict] = plan["sections"]
    n = len(sections)
    parts: List[str] = []
    titles: List[str] = []
    cost = 0.0
    for i, section in enumerate(sections):
        _check(cancel)
        base = 0.10 + 0.72 * i / n
        span = 0.72 / n

        def progress(chars: int, _base=base, _span=span, _title=section["title"], _i=i):
            # on estime une section a ~9000 caracteres pour la barre
            frac = min(0.97, chars / 9000.0)
            on_progress("Section %d/%d - %s" % (_i + 1, n, _title), _base + _span * frac)

        on_progress("Section %d/%d - %s" % (i + 1, n, section["title"]), base)
        res = cc.run(
            prompts.section_prompt(syl, course, plan, i, titles),
            model=model,
            system=("Vous redigez des cours de mathematiques en HTML. Vous ne "
                    "produisez que le fragment HTML demande, sans commentaire."),
            cancel=cancel,
            on_progress=progress,
        )
        cost += res.cost_usd
        parts.append(content.clean_html(res.text))
        titles.append(section["title"])
        content.write_body(course_id, "\n\n".join(parts))
    return "\n\n".join(parts), cost


def generate_exercises(syl: Syllabus, course_id: str, plan: dict, model: str,
                       on_progress: ProgressCb = _noop,
                       cancel: CancelCb = _never) -> tuple[dict, float]:
    course = syl.get(course_id)
    on_progress("QCM et demonstrations", 0.86)
    data, res = cc.run_json(
        prompts.exercises_prompt(syl, course, plan, content.digest(course_id)),
        model=model,
        system=("Vous concevez des exercices de mathematiques. Vous repondez "
                "uniquement en JSON valide."),
        schema=prompts.EXERCISES_SCHEMA,
        cancel=cancel,
    )
    qcm = data.get("qcm") or []
    proofs = data.get("proofs") or []
    if not qcm:
        raise cc.ClaudeError("Aucune question renvoyee.")
    for i, q in enumerate(qcm):
        q.setdefault("id", "q%d" % (i + 1))
        q["difficulty"] = int(q.get("difficulty") or 1)
        choices = q.get("choices") or []
        try:
            q["answer"] = int(q.get("answer", 0))
        except (TypeError, ValueError):
            q["answer"] = 0
        if not (0 <= q["answer"] < len(choices)):
            q["answer"] = 0
    for i, d in enumerate(proofs):
        d.setdefault("id", "d%d" % (i + 1))
        d["difficulty"] = int(d.get("difficulty") or 1)
        d.setdefault("hints", [])
        d.setdefault("steps", [])
    qcm.sort(key=lambda q: q["difficulty"])
    proofs.sort(key=lambda d: d["difficulty"])
    data = {"qcm": qcm, "proofs": proofs}
    content.write_json(course_id, content.EXOS, data)
    return data, res.cost_usd


def generate_course(course_id: str,
                    on_progress: ProgressCb = _noop,
                    cancel: CancelCb = _never,
                    with_exercises: bool = True,
                    syl: Optional[Syllabus] = None) -> dict:
    """Genere cours + exercices. Retourne les metadonnees."""
    syl = syl or load_syllabus()
    course = syl.get(course_id)
    if course is None:
        raise ValueError("cours inconnu : %s" % course_id)
    model_course = str(settings.get("model/course"))
    model_exos = str(settings.get("model/exercises"))
    started = time.time()
    cost = 0.0

    plan = generate_plan(syl, course_id, model_course, on_progress, cancel)
    cost += float(plan.get("_cost") or 0.0)

    _body, c = generate_sections(syl, course_id, plan, model_course, on_progress, cancel)
    cost += c

    if with_exercises:
        _exos, c = generate_exercises(syl, course_id, plan, model_exos, on_progress, cancel)
        cost += c

    duration = time.time() - started
    meta = {
        "course_id": course_id,
        "title": course.title,
        "generated_at": time.time(),
        "duration_s": round(duration, 1),
        "cost_usd": round(cost, 4),
        "model_course": model_course,
        "model_exercises": model_exos,
        "sections": [s["title"] for s in plan["sections"]],
        "left_as_exercise": plan.get("left_as_exercise", []),
    }
    content.write_json(course_id, content.META, meta)
    store.mark_generated(course_id, model_course, cost, duration)
    on_progress("Termine", 1.0)
    return meta


def regenerate_exercises(course_id: str,
                         on_progress: ProgressCb = _noop,
                         cancel: CancelCb = _never,
                         syl: Optional[Syllabus] = None) -> dict:
    syl = syl or load_syllabus()
    plan = content.read_plan(course_id)
    if plan is None:
        raise ValueError("Le cours doit etre genere avant ses exercices.")
    data, cost = generate_exercises(
        syl, course_id, plan, str(settings.get("model/exercises")), on_progress, cancel)
    meta = content.read_meta(course_id)
    meta["cost_usd"] = round(float(meta.get("cost_usd") or 0) + cost, 4)
    content.write_json(course_id, content.META, meta)
    on_progress("Termine", 1.0)
    return data
