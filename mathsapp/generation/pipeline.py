"""Chaine de generation d'un cours : plan -> sections -> exercices."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
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

    def context_for(index: int) -> tuple[str, str]:
        """Ce qui precede la section, et ce qui est traite ailleurs.

        Les sections sont redigees en parallele : sans ce contexte, chacune
        reintroduit les memes definitions, puisqu'elle ne connait que les
        titres des autres. Quand une section anterieure est deja ecrite, on
        donne ce qu'elle a reellement introduit ; sinon on se rabat sur ce que
        le plan lui assigne.
        """
        before, after = [], []
        for j, section in enumerate(sections):
            if j == index:
                continue
            written = parts[j]
            if j < index:
                if written:
                    items = content.section_items(written)
                    detail = ("\n".join("       - %s" % it for it in items)
                              if items else "       %s" % section.get("content", ""))
                else:
                    detail = "       %s" % section.get("content", "")
                before.append("  %d. %s\n%s" % (j + 1, section["title"], detail))
            else:
                after.append("  %d. %s — %s" % (j + 1, section["title"],
                                                section.get("content", "")))
        return "\n".join(before), "\n".join(after)

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

        covered, upcoming = context_for(index)
        access, source_text = source_access(plan, index)
        res = cc.run(
            prompts.section_prompt(syl, course, plan, index, titles[:index],
                                   covered, upcoming, source_text),
            model=model,
            system=("Vous redigez des cours de mathematiques en HTML. Vous ne "
                    "produisez que le fragment HTML demande, sans commentaire."),
            cancel=cancel,
            on_progress=progress,
            on_notice=notice,
            **access,
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


# Une proposition qui renvoie aux autres interdit de melanger l'ordre.
_POSITIONAL_RE = re.compile(
    r"ci-dessus|ci-dessous|aucune de ces|toutes les (?:réponses|propositions)|"
    r"\b(?:réponses?|propositions?)\s+[ABCD]\b", re.I)


def _plain(html_text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text)).strip()


def retag_exercises(qcm: List[dict], min_chars: int = 200) -> int:
    """Un « exercice » qui se resout de tete n'en est pas un.

    Le badge doit vouloir dire quelque chose : prends une feuille. On requalifie
    donc en question directe tout item marque exercice dont l'enonce est court
    ou dont la difficulte est faible.
    """
    changed = 0
    for question in qcm:
        if question.get("kind") != "exercice":
            continue
        short = len(_plain(question.get("question", ""))) < min_chars
        easy = int(question.get("difficulty") or 1) < 3
        if short or easy:
            question["kind"] = "direct"
            changed += 1
    return changed


def _shufflable(question: dict) -> bool:
    return not any(_POSITIONAL_RE.search(_plain(c)) for c in question.get("choices", []))


def rebalance_positions(qcm: List[dict], seed: int = 0) -> int:
    """Repartit la bonne reponse sur les quatre positions.

    Le modele place presque toujours la bonne reponse en A ou en B : sur les
    premiers cours produits, elle n'etait en D qu'une fois sur cent cinquante.
    On permute donc les propositions pour viser une repartition uniforme.
    """
    rng = random.Random(seed)
    moved = 0
    targets: List[int] = []
    for i in range(len(qcm)):
        if i % 4 == 0:
            block = [0, 1, 2, 3]
            rng.shuffle(block)
            targets.extend(block)
    for question, target in zip(qcm, targets):
        choices = question.get("choices") or []
        answer = question.get("answer", 0)
        if len(choices) < 2 or not (0 <= answer < len(choices)):
            continue
        if not _shufflable(question):
            continue
        target = min(target, len(choices) - 1)
        if target == answer:
            continue
        choices[answer], choices[target] = choices[target], choices[answer]
        question["answer"] = target
        moved += 1
    return moved


def length_offenders(qcm: List[dict], ratio: float = 1.35) -> List[dict]:
    """Questions ou la bonne reponse se reconnait a sa longueur."""
    out = []
    for question in qcm:
        choices = question.get("choices") or []
        answer = question.get("answer", 0)
        if len(choices) < 3 or not (0 <= answer < len(choices)):
            continue
        lengths = [len(_plain(c)) for c in choices]
        others = sorted(lengths[:answer] + lengths[answer + 1:])
        median = others[len(others) // 2] or 1
        if lengths[answer] == max(lengths) and lengths[answer] > ratio * median:
            out.append(question)
    return out


def repair_qcm_balance(syl: Syllabus, course_id: str, qcm: List[dict], model: str,
                       on_progress: ProgressCb = _noop,
                       cancel: CancelCb = _never) -> tuple[int, float]:
    """Reecrit les propositions desequilibrees. Retourne (corrigees, cout)."""
    course = syl.get(course_id)
    offenders = length_offenders(qcm)
    if len(offenders) < 2:
        return 0, 0.0
    on_progress("Équilibrage des propositions (%d questions)" % len(offenders), 0.93)
    try:
        data, res = cc.run_json(
            prompts.qcm_repair_prompt(course, offenders),
            model=model,
            system=("Vous corrigez des QCM de mathematiques. Vous repondez "
                    "uniquement en JSON valide."),
            schema=prompts.QCM_REPAIR_SCHEMA,
            cancel=cancel,
        )
    except cc.ClaudeError:
        return 0, 0.0
    by_id = {q["id"]: q for q in qcm}
    fixed = 0
    for item in data.get("questions", []):
        target = by_id.get(item.get("id"))
        choices = item.get("choices") or []
        if target is None or len(choices) != len(target["choices"]):
            continue
        try:
            answer = int(item.get("answer", 0))
        except (TypeError, ValueError):
            continue
        if not (0 <= answer < len(choices)):
            continue
        target["choices"] = choices
        target["answer"] = answer
        fixed += 1
    return fixed, res.cost_usd


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
        q["kind"] = "exercice" if str(q.get("kind", "")).lower().startswith("ex") else "direct"
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

    retag_exercises(qcm)
    cost = res.cost_usd
    _fixed, repair_cost = repair_qcm_balance(syl, course_id, qcm, model,
                                             on_progress, cancel)
    cost += repair_cost
    rebalance_positions(qcm, seed=abs(hash(course_id)) % 10000)

    data = {"qcm": qcm, "proofs": proofs}
    content.write_json(course_id, content.EXOS, data)
    return data, cost


def generate_quiz_set(course_id: str, model: Optional[str] = None,
                      on_progress: ProgressCb = _noop,
                      cancel: CancelCb = _never,
                      syl: Optional[Syllabus] = None) -> tuple[str, float]:
    """Produit une serie de QCM supplementaire. Retourne (identifiant, cout)."""
    syl = syl or load_syllabus()
    course = syl.get(course_id)
    if course is None:
        raise ValueError("cours inconnu : %s" % course_id)
    plan = content.read_plan(course_id)
    if plan is None or not content.has_course(course_id):
        raise ValueError("Le cours doit être rédigé avant une série de QCM.")
    model = model or str(settings.get("model/exercises"))
    existing = content.all_questions(course_id)
    on_progress("Nouvelle série de questions", 0.1)
    data, res = cc.run_json(
        prompts.extra_quiz_prompt(syl, course, plan, content.digest(course_id), existing),
        model=model,
        system=("Vous concevez des exercices de mathematiques. Vous repondez "
                "uniquement en JSON valide."),
        schema={"type": "object",
                "properties": {"qcm": prompts.EXERCISES_SCHEMA["properties"]["qcm"]},
                "required": ["qcm"]},
        cancel=cancel,
        on_progress=lambda n: on_progress("Nouvelle série de questions",
                                          min(0.85, 0.1 + n / 16000.0)),
        on_notice=lambda msg: on_progress("Nouvelle série — %s" % msg, 0.1),
    )
    qcm = data.get("qcm") or []
    if not qcm:
        raise cc.ClaudeError("Aucune question renvoyée.")

    set_id = content.next_quiz_set_id(course_id)
    known = {q["id"] for q in existing}
    for i, q in enumerate(qcm):
        base = str(q.get("id") or "q%d" % (i + 1))
        q["id"] = base if base not in known else "s%s-%s" % (set_id, base)
        known.add(q["id"])
        q["kind"] = "exercice" if str(q.get("kind", "")).lower().startswith("ex") else "direct"
        q["difficulty"] = max(1, min(5, int(q.get("difficulty") or 1)))
        choices = q.get("choices") or []
        try:
            q["answer"] = int(q.get("answer", 0))
        except (TypeError, ValueError):
            q["answer"] = 0
        if not (0 <= q["answer"] < len(choices)):
            q["answer"] = 0
    qcm.sort(key=lambda q: q["difficulty"])

    retag_exercises(qcm)
    cost = res.cost_usd
    _fixed, repair_cost = repair_qcm_balance(syl, course_id, qcm, model, on_progress, cancel)
    cost += repair_cost
    rebalance_positions(qcm, seed=abs(hash(course_id + set_id)) % 10000)

    content.add_quiz_set(course_id, qcm)
    on_progress("Terminé", 1.0)
    return set_id, cost


def pick_daily_courses(syl: Syllabus, statuses, count: int = 4) -> List[str]:
    """Choisit les cours du quiz du jour : les plus fragiles et les plus anciens."""
    from .. import store
    eligible = [c.id for c in syl.all()
                if statuses[c.id].has_exercises and statuses[c.id].answered > 0]
    if not eligible:
        eligible = [c.id for c in syl.all() if statuses[c.id].has_exercises]
    if not eligible:
        return []

    seen_at = {r["course_id"]: r["last"] for r in store.conn().execute(
        "SELECT course_id, MAX(updated_at) last FROM question_result GROUP BY course_id")}
    weak = sorted(eligible, key=lambda cid: statuses[cid].score_pct or 0)
    old = sorted(eligible, key=lambda cid: seen_at.get(cid, 0.0))

    picked: List[str] = []
    for source in (weak[:2], old[:2], weak[2:], old[2:]):
        for cid in source:
            if cid not in picked:
                picked.append(cid)
            if len(picked) >= count:
                return picked
    return picked[:count]


def generate_daily_quiz(day: Optional[str] = None, model: Optional[str] = None,
                        on_progress: ProgressCb = _noop,
                        cancel: CancelCb = _never,
                        syl: Optional[Syllabus] = None,
                        count: int = 10) -> tuple[str, float]:
    """Produit le quiz du jour. Retourne (jour, cout)."""
    from .. import gamify, status as st_mod
    syl = syl or load_syllabus()
    day = day or gamify.today()
    statuses = st_mod.compute(syl)
    course_ids = pick_daily_courses(syl, statuses)
    if not course_ids:
        raise ValueError("Aucun cours evalue : le quiz du jour a besoin de "
                         "chapitres deja travailles.")
    model = model or str(settings.get("model/exercises"))
    on_progress("Quiz du jour", 0.1)

    items = []
    for cid in course_ids:
        seen = [re.sub(r"<[^>]+>", " ", q.get("question", ""))
                for q in content.all_questions(cid)]
        items.append({"course": syl.get(cid),
                      "digest": content.digest(cid, limit=2600),
                      "seen": seen})

    data, res = cc.run_json(
        prompts.daily_quiz_prompt(syl, items, count),
        model=model,
        system=("Vous composez des quiz de revision en mathematiques. Vous "
                "repondez uniquement en JSON valide."),
        schema=prompts.DAILY_SCHEMA,
        cancel=cancel,
        on_progress=lambda n: on_progress("Quiz du jour", min(0.9, 0.1 + n / 20000.0)),
        on_notice=lambda msg: on_progress("Quiz du jour — %s" % msg, 0.1),
    )
    qcm = data.get("qcm") or []
    if not qcm:
        raise cc.ClaudeError("Aucune question renvoyee.")

    titles = {syl.get(cid).title: cid for cid in course_ids}
    for i, q in enumerate(qcm):
        q["id"] = "d%s-%d" % (day.replace("-", ""), i + 1)
        q["kind"] = "exercice" if str(q.get("kind", "")).lower().startswith("ex") else "direct"
        q["difficulty"] = max(1, min(5, int(q.get("difficulty") or 1)))
        choices = q.get("choices") or []
        try:
            q["answer"] = int(q.get("answer", 0))
        except (TypeError, ValueError):
            q["answer"] = 0
        if not (0 <= q["answer"] < len(choices)):
            q["answer"] = 0
        # on rattache la question a son cours, pour le suivi et l'XP
        q["course_id"] = titles.get((q.get("section") or "").strip(), course_ids[i % len(course_ids)])
        q["section"] = syl.title(q["course_id"])

    retag_exercises(qcm)
    cost = res.cost_usd
    rebalance_positions(qcm, seed=abs(hash(day)) % 10000)
    content.write_daily(day, {"day": day, "courses": course_ids, "qcm": qcm,
                              "created_at": time.time()})
    on_progress("Termine", 1.0)
    return day, cost


def generate_sheet(course_id: str, model: Optional[str] = None,
                   on_progress: ProgressCb = _noop,
                   cancel: CancelCb = _never,
                   syl: Optional[Syllabus] = None) -> float:
    """Produit la fiche de revision d'un cours deja redige. Retourne le cout."""
    syl = syl or load_syllabus()
    course = syl.get(course_id)
    if course is None:
        raise ValueError("cours inconnu : %s" % course_id)
    if not content.has_course(course_id):
        raise ValueError("Le cours doit etre redige avant sa fiche.")
    model = model or str(settings.get("model/sheet") or settings.get("model/exercises"))
    on_progress("Fiche de révision", 0.05)
    res = cc.run(
        prompts.sheet_prompt(syl, course, content.read_plan(course_id),
                             content.substance(course_id)),
        model=model,
        system=("Vous condensez des cours de mathematiques en fiches de revision. "
                "Vous ne produisez que le fragment HTML demande, sans commentaire."),
        cancel=cancel,
        on_progress=lambda n: on_progress("Fiche de révision", min(0.95, 0.05 + n / 9000.0)),
        on_notice=lambda msg: on_progress("Fiche de révision — %s" % msg, 0.05),
    )
    content.write_sheet(course_id, content.clean_html(res.text))
    on_progress("Terminé", 1.0)
    return res.cost_usd


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

    if settings.get("gen/auto_sheet") and not content.has_sheet(course_id):
        try:
            cost += generate_sheet(course_id, None, on_progress, cancel, syl)
        except cc.ClaudeError as exc:
            # la fiche est un supplement : son echec ne doit pas perdre le cours
            on_progress("Fiche non produite : %s" % exc, 0.98)

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


# ---------------------------------------------------------------------------
# TD : lecture du sujet et correction commentée
# ---------------------------------------------------------------------------
def normalize_td_structure(raw: dict, syl: Syllabus) -> dict:
    """Nettoie la transcription d'un sujet : cours inconnus retirés, bornes."""
    items = []
    for i, ex in enumerate(raw.get("exercises") or []):
        statement = (ex.get("statement") or "").strip()
        if not statement:
            continue
        courses: List[str] = []
        for cid in ex.get("courses") or []:
            cid = str(cid).strip()
            if cid in syl.courses and cid not in courses:
                courses.append(cid)
        try:
            difficulty = int(ex.get("difficulty") or 3)
        except (TypeError, ValueError):
            difficulty = 3
        number = str(ex.get("number") or i + 1).strip()
        items.append({
            "number": number,
            "title": (ex.get("title") or "").strip() or "Exercice %s" % number,
            "statement": content.clean_html(statement),
            "courses": courses[:6],
            "key_results": [str(r).strip() for r in (ex.get("key_results") or [])
                            if str(r).strip()][:8],
            "difficulty": max(1, min(5, difficulty)),
        })
    return {"title": (raw.get("title") or "").strip() or "TD",
            "subject": (raw.get("subject") or "").strip(),
            "exercises": items}


def structure_td(td_id: str, model: Optional[str] = None,
                 on_progress: ProgressCb = _noop, cancel: CancelCb = _never,
                 syl: Optional[Syllabus] = None) -> dict:
    """Lit le PDF du sujet (formules comprises) et le découpe en exercices."""
    from .. import td as td_mod
    syl = syl or load_syllabus()
    src = td_mod.source_path(td_id)
    if not src.exists():
        raise ValueError("Sujet introuvable : %s" % src)
    model = model or str(settings.get("model/exercises"))
    folder = str(td_mod.td_dir(td_id))
    on_progress("Lecture du sujet", 0.03)
    access, document = {}, ""
    if cc.uses_tools():
        access = {"tools": "Read", "add_dirs": [folder], "cwd": folder}
    else:
        from .. import pdf_text
        document = pdf_text.extract(src)
    raw, res = cc.run_json(
        prompts.td_structure_prompt(syl, str(src), document),
        model=model,
        system=("Vous transcrivez fidèlement des sujets de mathématiques. "
                "Vous répondez uniquement en JSON valide."),
        schema=prompts.TD_SCHEMA,
        cancel=cancel,
        **access,
        on_progress=lambda n: on_progress("Lecture du sujet", min(0.14, 0.03 + n / 60000.0)),
        on_notice=lambda msg: on_progress("Lecture du sujet — %s" % msg, 0.03),
    )
    data = normalize_td_structure(raw, syl)
    if not data["exercises"]:
        raise cc.ClaudeError("Aucun exercice n'a pu être lu dans le sujet.")
    td_mod.write_structure(td_id, data)
    td_mod.update_meta(td_id, structured_at=time.time(), structure_model=model,
                       structure_cost=round(res.cost_usd, 4),
                       exercise_count=len(data["exercises"]))
    return data


def td_materials(syl: Syllabus, exercise: dict, budget: int = 14000) -> List[dict]:
    """Matière des cours rattachés : contenu rédigé s'il existe, sinon programme."""
    materials, used = [], 0
    for cid in exercise.get("courses", []):
        course = syl.get(cid)
        if course is None:
            continue
        generated = content.has_course(cid)
        substance = ""
        if generated and used < budget:
            substance = content.substance(cid, limit=min(6000, budget - used))
            used += len(substance)
        materials.append({"course": course, "generated": generated, "substance": substance})
    return materials


def correct_td(td_id: str, model: Optional[str] = None,
               on_progress: ProgressCb = _noop, cancel: CancelCb = _never,
               syl: Optional[Syllabus] = None, force: bool = False) -> tuple:
    """Corrige les exercices en parallèle, avec reprise. Retourne (corrigés, coût)."""
    from .. import td as td_mod
    syl = syl or load_syllabus()
    data = td_mod.read_structure(td_id)
    if not data or not data.get("exercises"):
        raise ValueError("Le sujet doit être lu avant d'être corrigé.")
    items = data["exercises"]
    n = len(items)
    title = data.get("title") or td_id
    model = model or str(settings.get("model/course"))
    fingerprints = [td_mod.exercise_fingerprint(ex) for ex in items]

    done: List[Optional[str]] = [None] * n
    if not force:
        for i in range(n):
            done[i] = td_mod.read_correction(td_id, i, fingerprints[i])
    todo = [i for i in range(n) if done[i] is None]
    finished = n - len(todo)
    chars: Dict[int, int] = {}
    started: Dict[int, float] = {}
    costs = [0.0] * n
    lock = threading.Lock()

    def report() -> None:
        partial = sum(min(0.98, chars.get(i, 0) / 24000.0)
                      for i in todo if done[i] is None and i in started)
        frac = 0.15 + 0.85 * (finished + partial) / max(1, n)
        running = [i for i in todo if done[i] is None and i in started]
        if running:
            i = running[0]
            label = ("Exercice %s (%d/%d) — %s · %s caractères · %s"
                     % (items[i].get("number", i + 1), i + 1, n, items[i].get("title", ""),
                        _fmt_thousands(chars.get(i, 0)), _fmt_clock(time.time() - started[i])))
            if len(running) > 1:
                label += "  (+%d en parallèle)" % (len(running) - 1)
        else:
            label = "Exercices corrigés : %d/%d" % (finished, n)
        on_progress(label, frac)

    report()

    def work(i: int) -> None:
        nonlocal finished
        _check(cancel)
        with lock:
            started[i] = time.time()
            chars[i] = 0
        report()

        def progress(count: int, _i=i) -> None:
            with lock:
                chars[_i] = count
            report()

        res = cc.run(
            prompts.td_correction_prompt(syl, title, items[i], td_materials(syl, items[i]), i, n),
            model=model,
            system=("Vous rédigez des corrections commentées de TD de mathématiques en "
                    "HTML. Vous ne produisez que le fragment HTML demandé."),
            cancel=cancel,
            on_progress=progress,
            on_notice=lambda msg, _i=i: on_progress(
                "Exercice %d/%d — %s" % (_i + 1, n, msg), 0.15 + 0.85 * finished / max(1, n)),
        )
        body = content.clean_html(res.text)
        with lock:
            done[i] = body
            costs[i] = res.cost_usd
            finished += 1
            td_mod.write_correction(td_id, i, fingerprints[i], body)
        report()

    workers = max(1, min(6, int(settings.get("gen/section_parallel") or 3), len(todo) or 1))
    t0 = time.time()
    if todo:
        if workers == 1:
            for i in todo:
                work(i)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for future in as_completed([pool.submit(work, i) for i in todo]):
                    future.result()

    cost = sum(costs)
    meta = td_mod.read_meta(td_id)
    td_mod.update_meta(td_id, corrected_at=time.time(), correction_model=model,
                       correction_cost=round(float(meta.get("correction_cost") or 0) + cost, 4),
                       correction_duration=round(time.time() - t0, 1))
    on_progress("Terminé", 1.0)
    return len(todo), cost


def run_td(td_id: str, on_progress: ProgressCb = _noop, cancel: CancelCb = _never,
           syl: Optional[Syllabus] = None) -> dict:
    """Lit le sujet si nécessaire, puis corrige ce qui ne l'est pas encore."""
    from .. import td as td_mod
    syl = syl or load_syllabus()
    cost = 0.0
    if not td_mod.exercises(td_id):
        structure_td(td_id, None, on_progress, cancel, syl)
        cost += float(td_mod.read_meta(td_id).get("structure_cost") or 0)
    corrected, spent = correct_td(td_id, None, on_progress, cancel, syl)
    cost += spent
    state = td_mod.state(td_id)
    return {"exercises": state["total"], "corrected": corrected,
            "cost": cost, "complete": state["complete"]}


# ---------------------------------------------------------------------------
# Rappel ciblé
# ---------------------------------------------------------------------------
def missed_questions(course_id: str, limit: int = 6) -> List[dict]:
    """Questions du cours actuellement ratées, les plus tenaces d'abord."""
    from .. import store
    index = content.question_index()
    out = []
    for r in store.conn().execute(
            "SELECT set_id, question_id, tries FROM question_result"
            " WHERE course_id = ? AND last_ok = 0 ORDER BY tries DESC, updated_at DESC",
            (course_id,)):
        q = index.get((course_id, r["set_id"], r["question_id"]))
        if q is not None:
            out.append(dict(q, tries=r["tries"]))
        if len(out) >= limit:
            break
    return out


def generate_refresher(course_id: str, day: Optional[str] = None,
                       model: Optional[str] = None,
                       on_progress: ProgressCb = _noop, cancel: CancelCb = _never,
                       syl: Optional[Syllabus] = None, count: int = 5) -> tuple[str, float]:
    """Cinq questions neuves sur ce qui coince dans un cours. Retourne (jour, coût)."""
    from .. import gamify
    syl = syl or load_syllabus()
    course = syl.get(course_id)
    if course is None:
        raise ValueError("Cours inconnu : %s" % course_id)
    day = day or gamify.today()
    model = model or str(settings.get("model/exercises"))
    on_progress("Rappel ciblé", 0.1)

    missed = missed_questions(course_id)
    seen = [re.sub(r"<[^>]+>", " ", q.get("question", ""))
            for q in content.all_questions(course_id)]
    data, res = cc.run_json(
        prompts.refresher_prompt(syl, course, content.digest(course_id, limit=5000),
                                 missed, seen, count),
        model=model,
        system=("Vous composez des rappels de cours ciblés en mathématiques. Vous "
                "répondez uniquement en JSON valide."),
        schema=prompts.DAILY_SCHEMA,
        cancel=cancel,
        on_progress=lambda n: on_progress("Rappel ciblé", min(0.9, 0.1 + n / 9000.0)),
        on_notice=lambda msg: on_progress("Rappel ciblé — %s" % msg, 0.1),
    )
    qcm = (data.get("qcm") or [])[:count]
    if not qcm:
        raise cc.ClaudeError("Aucune question renvoyée.")
    for i, q in enumerate(qcm):
        q["id"] = "r%s-%d" % (day.replace("-", ""), i + 1)
        q["kind"] = "exercice" if str(q.get("kind", "")).lower().startswith("ex") else "direct"
        try:
            q["difficulty"] = max(1, min(5, int(q.get("difficulty") or 1)))
        except (TypeError, ValueError):
            q["difficulty"] = 2
        choices = q.get("choices") or []
        try:
            q["answer"] = int(q.get("answer", 0))
        except (TypeError, ValueError):
            q["answer"] = 0
        if not (0 <= q["answer"] < len(choices)):
            q["answer"] = 0
        q["course_id"] = course_id
    retag_exercises(qcm)
    rebalance_positions(qcm, seed=abs(hash((day, course_id))) % 10000)
    content.write_refresher(day, course_id, {
        "day": day, "course_id": course_id, "qcm": qcm,
        "missed": [q.get("id") for q in missed], "created_at": time.time(),
        "cost_usd": round(res.cost_usd, 4)})
    on_progress("Terminé", 1.0)
    return day, res.cost_usd


# ---------------------------------------------------------------------------
# Cours importés depuis un PDF
# ---------------------------------------------------------------------------
def source_access(plan: dict, index: int) -> tuple:
    """Comment la section atteint son PDF : outil Read, ou texte extrait ici.

    `claude` lit le PDF lui-meme ; les autres moteurs recoivent le texte des
    pages de la section.
    """
    source = plan.get("source") or {}
    pdf = source.get("pdf")
    if not pdf or not os.path.exists(pdf):
        return {}, ""
    if cc.uses_tools():
        return source_tools(plan), ""
    from .. import pdf_text
    pages = (plan.get("sections") or [{}])[index].get("pages") or ""
    return {}, pdf_text.extract(pdf, pages, limit=60000)


def source_tools(plan: dict) -> dict:
    """Un cours importé relit son PDF : outil Read, limité au dossier du document."""
    pdf = (plan.get("source") or {}).get("pdf")
    if not pdf or not os.path.exists(pdf):
        return {}
    folder = os.path.dirname(pdf)
    return {"tools": "Read", "add_dirs": [folder], "cwd": folder}


def read_course_document(doc: str, model: Optional[str] = None,
                         on_progress: ProgressCb = _noop, cancel: CancelCb = _never,
                         syl: Optional[Syllabus] = None) -> dict:
    """Lit tout le PDF et en tire le plan détaillé et les exercices."""
    from .. import course_import, td as td_mod
    syl = syl or load_syllabus()
    src = td_mod.source_path(doc)
    folder = str(td_mod.td_dir(doc))
    model = model or str(settings.get("model/exercises"))
    on_progress("Lecture du document", 0.01)
    access, document = {}, ""
    if cc.uses_tools():
        access = {"tools": "Read", "add_dirs": [folder], "cwd": folder}
    else:
        from .. import pdf_text
        document = pdf_text.extract(src)
    raw, res = cc.run_json(
        prompts.course_import_prompt(syl, str(src), document),
        model=model,
        system=("Vous analysez des cours de mathématiques pour les réécrire. "
                "Vous répondez uniquement en JSON valide."),
        schema=prompts.COURSE_IMPORT_SCHEMA,
        cancel=cancel,
        **access,
        on_progress=lambda n: on_progress("Lecture du document", min(0.05, 0.01 + n / 400000.0)),
        on_notice=lambda msg: on_progress("Lecture du document — %s" % msg, 0.01),
    )
    data = course_import.normalize_import(raw, syl)
    if not data["sections"]:
        raise cc.ClaudeError("Aucune section n'a pu être tirée du document.")
    course_import.write_import(doc, data)
    td_mod.update_meta(doc, read_cost=round(res.cost_usd, 4), read_model=model,
                       title=data["title"])
    return data


def run_course_import(doc: str, on_progress: ProgressCb = _noop, cancel: CancelCb = _never,
                      syl: Optional[Syllabus] = None) -> dict:
    """Tout l'import, reprenable à chaque étape : lecture, inscription, cours, corrections."""
    from .. import course_import, td as td_mod
    from ..syllabus import reload as reload_syllabus
    syl = syl or load_syllabus()
    cost = 0.0

    data = course_import.read_import(doc)
    if data is None:
        data = read_course_document(doc, None, on_progress, cancel, syl)
        cost += float(td_mod.read_meta(doc).get("read_cost") or 0)

    course_id = course_import.register(doc, syl)
    syl = reload_syllabus()

    def scaled(lo: float, hi: float) -> ProgressCb:
        return lambda label, frac: on_progress(label, lo + (hi - lo) * max(0.0, min(1.0, frac)))

    if not content.is_complete(course_id):
        meta = generate_course(course_id, scaled(0.06, 0.82), cancel, True, syl)
        cost += float(meta.get("cost_usd") or 0)

    corrected = 0
    if td_mod.exercises(doc):
        corrected, spent = correct_td(doc, None, scaled(0.82, 1.0), cancel, syl)
        cost += spent
    on_progress("Terminé", 1.0)
    plan = content.read_plan(course_id) or {}
    return {"course_id": course_id, "title": syl.title(course_id), "cost": cost,
            "sections": len(plan.get("sections") or []),
            "exercises": td_mod.state(doc)["corrected"], "corrected_now": corrected}
