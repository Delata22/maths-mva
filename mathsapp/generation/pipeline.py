"""Chaine de generation d'un cours : plan -> sections -> exercices."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional

from .. import content, settings, store
from ..syllabus import Syllabus, load as load_syllabus
from . import claude_cli as cc
from . import prompts

ProgressCb = Callable[[str, float], None]
CancelCb = Callable[[], bool]


def _noop(_label: str, _frac: float) -> None:
    pass


def _fmt_thousands(n: int) -> str:
    return "{:,}".format(n).replace(",", " ")


def _fmt_clock(seconds: float) -> str:
    seconds = int(seconds)
    return "%d:%02d" % (seconds // 60, seconds % 60)


def _never() -> bool:
    return False


# Une seule exception d'annulation, qu'elle vienne du CLI ou de la chaine.
GenerationCancelled = cc.Cancelled


def _check(cancel: CancelCb) -> None:
    if cancel():
        raise GenerationCancelled("Génération annulée.")


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
        on_notice=lambda msg: on_progress("Plan du cours — %s" % msg, 0.02),
    )
    sections = plan.get("sections") or []
    if not sections:
        raise cc.ClaudeError("Le plan renvoyé ne contient aucune section.")
    plan.setdefault("proved_in_course", [])
    plan.setdefault("left_as_exercise", [])
    plan["_cost"] = res.cost_usd
    content.write_json(course_id, content.PLAN, plan)
    return plan


def plan_fingerprint(plan: dict) -> str:
    """Identifie un plan par ses sections, pour savoir si le cache est valide."""
    payload = json.dumps([[sec.get("id"), sec.get("title"), sec.get("content")]
                          for sec in plan.get("sections", [])],
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def generate_sections(syl: Syllabus, course_id: str, plan: dict, model: str,
                      on_progress: ProgressCb = _noop,
                      cancel: CancelCb = _never) -> tuple[str, float]:
    """Redige toutes les sections, en parallele et de facon reprenable.

    Chaque section est ecrite dans son propre fichier : une generation
    interrompue reprend la ou elle s'etait arretee au lieu de tout refaire.
    """
    course = syl.get(course_id)
    sections: List[dict] = plan["sections"]
    n = len(sections)
    fingerprint = plan_fingerprint(plan)
    titles = [sec["title"] for sec in sections]
    parts: List[Optional[str]] = [None] * n
    costs: List[float] = [0.0] * n
    chars: Dict[int, int] = {}
    started_at: Dict[int, float] = {}

    for i in range(n):
        cached = content.read_section(course_id, i, fingerprint)
        if cached:
            parts[i] = cached
            chars[i] = len(cached)

    todo = [i for i in range(n) if parts[i] is None]
    done_count = n - len(todo)
    lock = threading.Lock()

    def flush() -> None:
        """Ecrit le corps du cours avec ce qui est deja pret."""
        content.write_body(course_id, "\n\n".join(p for p in parts if p))

    def expected_length() -> float:
        """Longueur attendue d'une section, mesurée plutôt que devinée.

        L'estimation etait figee a 9000 caracteres alors qu'une section en fait
        environ 28000 : la barre saturait apres un tiers du travail et donnait
        l'impression que la generation etait bloquee.
        """
        written = sorted(len(p) for p in parts if p)
        if written:
            return max(8000.0, float(written[len(written) // 2]))
        return 26000.0

    def report() -> None:
        target = expected_length()
        partial = sum(min(0.98, chars.get(i, 0) / target)
                      for i in todo if parts[i] is None)
        frac = 0.10 + 0.72 * (done_count + partial) / max(1, n)
        running = [i for i in todo if parts[i] is None and chars.get(i)]
        if running:
            first = running[0]
            elapsed = time.time() - started_at.get(first, time.time())
            # on affiche des caracteres et un chronometre : meme quand la barre
            # bouge peu, on doit pouvoir verifier d'un coup d'oeil que ca avance
            label = ("Section %d/%d — %s · %s caractères · %s"
                     % (first + 1, n, titles[first],
                        _fmt_thousands(chars.get(first, 0)), _fmt_clock(elapsed)))
            if len(running) > 1:
                label += "  (+%d en parallèle)" % (len(running) - 1)
        else:
            label = "Sections %d/%d" % (done_count, n)
        on_progress(label, frac)

    if done_count:
        flush()
    report()

    def work(index: int) -> None:
        nonlocal done_count
        _check(cancel)
        with lock:
            started_at[index] = time.time()
            chars.setdefault(index, 0)
        report()

        def progress(count: int, _i=index) -> None:
            with lock:
                chars[_i] = count
            report()

        def notice(msg: str, _i=index) -> None:
            on_progress("Section %d/%d — %s" % (_i + 1, n, msg),
                        0.10 + 0.72 * done_count / max(1, n))

        res = cc.run(
            prompts.section_prompt(syl, course, plan, index, titles[:index]),
            model=model,
            system=("Vous redigez des cours de mathematiques en HTML. Vous ne "
                    "produisez que le fragment HTML demande, sans commentaire."),
            cancel=cancel,
            on_progress=progress,
            on_notice=notice,
        )
        body = content.clean_html(res.text)
        with lock:
            parts[index] = body
            costs[index] = res.cost_usd
            done_count += 1
            content.write_section(course_id, index, fingerprint, body)
            flush()
        report()

    workers = max(1, min(6, int(settings.get("gen/section_parallel") or 3), len(todo) or 1))
    if todo:
        if workers == 1:
            for index in todo:
                work(index)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(work, index) for index in todo]
                for future in as_completed(futures):
                    future.result()   # laisse remonter la premiere erreur

    missing = [i for i in range(n) if parts[i] is None]
    if missing:
        raise cc.ClaudeError("Sections manquantes : %s"
                             % ", ".join(titles[i] for i in missing))
    flush()
    return "\n\n".join(parts), sum(costs)


def generate_exercises(syl: Syllabus, course_id: str, plan: dict, model: str,
                       on_progress: ProgressCb = _noop,
                       cancel: CancelCb = _never) -> tuple[dict, float]:
    course = syl.get(course_id)
    on_progress("QCM et démonstrations", 0.86)
    data, res = cc.run_json(
        prompts.exercises_prompt(syl, course, plan, content.digest(course_id)),
        model=model,
        system=("Vous concevez des exercices de mathematiques. Vous repondez "
                "uniquement en JSON valide."),
        schema=prompts.EXERCISES_SCHEMA,
        cancel=cancel,
        on_notice=lambda msg: on_progress("QCM et démonstrations — %s" % msg, 0.86),
    )
    qcm = data.get("qcm") or []
    proofs = data.get("proofs") or []
    if not qcm:
        raise cc.ClaudeError("Aucune question renvoyée.")
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
                    syl: Optional[Syllabus] = None,
                    model_course: Optional[str] = None,
                    model_exercises: Optional[str] = None) -> dict:
    """Genere cours + exercices. Retourne les metadonnees."""
    syl = syl or load_syllabus()
    course = syl.get(course_id)
    if course is None:
        raise ValueError("cours inconnu : %s" % course_id)
    model_course = str(model_course or settings.get("model/course"))
    model_exos = str(model_exercises or settings.get("model/exercises"))
    started = time.time()
    cost = 0.0

    plan = content.read_plan(course_id)
    if plan and plan.get("sections"):
        # reprise : on garde le plan existant, donc les sections deja ecrites
        on_progress("Reprise du plan existant", 0.08)
    else:
        plan = generate_plan(syl, course_id, model_course, on_progress, cancel)
        cost += float(plan.get("_cost") or 0.0)

    _body, c = generate_sections(syl, course_id, plan, model_course, on_progress, cancel)
    cost += c

    if with_exercises and not content.has_exercises(course_id):
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
    on_progress("Terminé", 1.0)
    return meta


def regenerate_exercises(course_id: str,
                         on_progress: ProgressCb = _noop,
                         cancel: CancelCb = _never,
                         syl: Optional[Syllabus] = None) -> dict:
    syl = syl or load_syllabus()
    plan = content.read_plan(course_id)
    if plan is None:
        raise ValueError("Le cours doit être généré avant ses exercices.")
    data, cost = generate_exercises(
        syl, course_id, plan, str(settings.get("model/exercises")), on_progress, cancel)
    meta = content.read_meta(course_id)
    meta["cost_usd"] = round(float(meta.get("cost_usd") or 0) + cost, 4)
    content.write_json(course_id, content.META, meta)
    on_progress("Terminé", 1.0)
    return data


def propose_syllabus(request: str, count: int = 10,
                     domain_hint: Optional[str] = None,
                     level_hint: Optional[str] = None,
                     model: Optional[str] = None,
                     on_progress: ProgressCb = _noop,
                     cancel: CancelCb = _never,
                     syl: Optional[Syllabus] = None) -> tuple[dict, List[str], str]:
    """Propose une extension du syllabus. Retourne (proposition, remarques, notes)."""
    from .. import syllabus_extra
    syl = syl or load_syllabus()
    model = model or str(settings.get("model/course"))
    on_progress("Conception du syllabus", 0.15)
    raw, res = cc.run_json(
        prompts.syllabus_prompt(syl, request, count, domain_hint, level_hint),
        model=model,
        system=("Vous concevez des syllabus de mathematiques et d'apprentissage. "
                "Vous repondez uniquement en JSON valide."),
        schema=prompts.SYLLABUS_SCHEMA,
        cancel=cancel,
        on_progress=lambda n: on_progress("Conception du syllabus", min(0.9, 0.15 + n / 14000.0)),
        on_notice=lambda msg: on_progress("Conception du syllabus — %s" % msg, 0.15),
    )
    batch, notes = syllabus_extra.normalize(raw)
    on_progress("Terminé", 1.0)
    return batch, notes, (raw.get("notes") or "").strip()
