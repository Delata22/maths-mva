#!/usr/bin/env python3
"""Verification de bout en bout, sans interface visible.

  python tools/selftest.py           # tout sauf les appels au modele
  python tools/selftest.py --chat    # ajoute un vrai aller-retour avec Claude

Verifie : le syllabus et son graphe, la base, l'assemblage des pages, le pont
JavaScript (selection de texte, aide a la demonstration, fin de QCM, statut
d'une demonstration), et les vues principales.
"""
from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-logging --no-sandbox")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((ok, name, detail))
    print("%s %s%s" % ("  ok  " if ok else " ECHEC", name, ("  — %s" % detail) if detail else ""))
    return ok


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(predicate, timeout_ms: int = 15000, step: int = 100) -> bool:
    elapsed = 0
    while elapsed < timeout_ms:
        if predicate():
            return True
        wait(step)
        elapsed += step
    return predicate()


def test_syllabus() -> None:
    from mathsapp.syllabus import load
    syl = load()
    check("syllabus charge", len(syl.courses) > 200 and len(syl.domains) > 20,
          "%d cours, %d domaines, %d parcours"
          % (len(syl.courses), len(syl.domains), len(syl.tracks)))
    check("parcours rattaches a un groupe connu",
          all(t.group in syl.track_groups for t in syl.tracks.values()),
          str([t.id for t in syl.tracks.values() if t.group not in syl.track_groups]))
    empty = [d for d in syl.domain_order if not syl.by_domain(d)]
    check("aucun domaine vide", not empty, str(empty))
    rank = syl.topo_rank
    bad = [(c.id, p) for c in syl.all() for p in c.prereqs if rank(p) >= rank(c.id)]
    check("ordre topologique coherent", not bad, str(bad[:3]))
    import re
    non_ascii = [c.id for c in syl.all() if not re.fullmatch(r"[a-z0-9-]+", c.id)]
    check("identifiants en ASCII", not non_ascii, str(non_ascii[:3]))
    orphans = [c.id for c in syl.all() for p in c.prereqs if p not in syl.courses]
    check("prerequis tous definis", not orphans, str(orphans[:3]))
    for tid in syl.tracks:
        track = syl.tracks[tid]
        path = syl.track_path(tid)
        inside = set(path)
        seen: set = set()
        ok = True
        for cid in path:
            # parcours calcule : tous les prerequis le precedent. Parcours a liste
            # choisie (express) : il saute volontairement des prerequis, mais
            # ceux qu'il contient, directs ou non, doivent venir avant.
            needed = (syl.get(cid).prereqs if not track.courses
                      else [p for p in syl.ancestors(cid) if p in inside])
            if any(p not in seen for p in needed):
                ok = False
                break
            seen.add(cid)
        if track.courses:
            ok = ok and sorted(path) == sorted(dict.fromkeys(track.courses))
        check("parcours %s ordonne" % tid, ok, "%d cours" % len(path))


def test_syllabus_extra() -> None:
    """Surcouche : validation, fusion, rechargement, retrait."""
    from mathsapp import syllabus, syllabus_extra

    backup = syllabus_extra.read_extra()
    base_count = len(syllabus.load().courses)
    try:
        batch = {
            "domains": [{"id": "selftest", "name": "Domaine de test",
                         "description": "d", "color": "#123456"}],
            "courses": [
                {"id": "st-un", "title": "Cours un", "domain": "selftest", "level": 3,
                 "prereqs": ["al-svd"], "summary": "s", "objectives": ["o"], "keywords": ["k"]},
                {"id": "st-deux", "title": "Cours deux", "domain": "selftest", "level": 4,
                 "prereqs": ["st-un", "inexistant-xyz"], "summary": "s",
                 "objectives": ["o"], "keywords": ["k"]},
                {"id": "AL SVD !", "title": "Décomposition en valeurs singulières (SVD)",
                 "domain": "selftest", "level": 3, "prereqs": [], "summary": "s",
                 "objectives": [], "keywords": []},
            ],
            "tracks": [{"id": "st-track", "title": "Parcours test", "goal": "st-deux",
                        "extra": ["st-un"]}],
        }
        clean, notes = syllabus_extra.normalize(batch)
        check("proposition normalisee", len(clean["courses"]) == 2,
              "%d cours retenus" % len(clean["courses"]))
        check("doublon ecarte",
              any("existe déjà" in n for n in notes)
              and all(c["id"] != "al-svd" for c in clean["courses"]),
              str(notes[:2]))
        check("prerequis inconnu retire",
              all("inexistant-xyz" not in c["prereqs"] for c in clean["courses"]))
        check("prerequis interne conserve",
              "st-un" in dict((c["id"], c) for c in clean["courses"])["st-deux"]["prereqs"])

        cyclic = {"domains": [], "courses": [
            {"id": "cy-a", "title": "A", "domain": "ml", "level": 3, "prereqs": ["cy-b"],
             "summary": "s", "objectives": [], "keywords": []},
            {"id": "cy-b", "title": "B", "domain": "ml", "level": 3, "prereqs": ["cy-a"],
             "summary": "s", "objectives": [], "keywords": []}], "tracks": []}
        cleaned_cycle, _ = syllabus_extra.normalize(cyclic)
        check("cycle refuse", bool(syllabus_extra.check(cleaned_cycle)),
              str(syllabus_extra.check(cleaned_cycle)))

        errors = syllabus_extra.add(clean)
        check("fusion acceptee", not errors, str(errors))
        syl = syllabus.reload()
        check("cours ajoutes visibles", len(syl.courses) == base_count + 2,
              "%d cours" % len(syl.courses))
        check("domaine ajoute visible", "selftest" in syl.domains)
        check("cours marque comme ajoute", syl.get("st-un").custom)
        check("graphe coherent apres ajout",
              syl.get("st-deux").depth > syl.get("st-un").depth)
        check("parcours ajoute", "st-track" in syl.tracks
              and len(syl.track_path("st-track")) > 2)

        removed = syllabus_extra.remove_courses(["st-un", "st-deux"])
        syl = syllabus.reload()
        check("retrait effectif", removed == 2 and len(syl.courses) == base_count,
              "%d cours" % len(syl.courses))
        check("domaine orphelin nettoye", "selftest" not in syl.domains)
    finally:
        syllabus_extra.write_extra(backup)
        syllabus.reload()


def test_prompts_integrity() -> None:
    """Tout ce que le code appelle dans prompts doit exister et s'executer.

    Un remplacement de texte trop large a deja supprime huit definitions de
    prompts.py sans qu'aucun test ne le voie : la generation d'exercices, les
    fiches, les series de QCM et l'extension du syllabus plantaient au premier
    appel. Ce test couvre les deux angles : les references, et l'execution.
    """
    import re
    from mathsapp import content
    from mathsapp.generation import prompts
    from mathsapp.syllabus import load

    root = pathlib.Path(__file__).resolve().parent.parent
    referenced = set()
    for path in list((root / "mathsapp").rglob("*.py")) + list((root / "tools").rglob("*.py")):
        if path.name == "selftest.py":
            continue
        referenced.update(re.findall(r"\bprompts\.([A-Za-z_][A-Za-z0-9_]*)",
                                     path.read_text(encoding="utf-8")))
    missing = sorted(name for name in referenced if not hasattr(prompts, name))
    check("toute reference a prompts existe", not missing,
          "%d references, manquantes : %s" % (len(referenced), missing))

    syl = load()
    cid = next((c.id for c in syl.all()
                if content.has_exercises(c.id) and content.read_plan(c.id)), None)
    if cid is None:
        check("prompts : aucun cours genere, execution non testee", True)
        return
    course, plan = syl.get(cid), content.read_plan(cid)
    questions = content.quiz_sets(cid)[0]["qcm"][:3]
    builders = {
        "plan_prompt": lambda: prompts.plan_prompt(syl, course),
        "section_prompt": lambda: prompts.section_prompt(syl, course, plan, 1,
                                                         [plan["sections"][0]["title"]]),
        "exercises_prompt": lambda: prompts.exercises_prompt(syl, course, plan,
                                                             content.digest(cid)),
        "extra_quiz_prompt": lambda: prompts.extra_quiz_prompt(syl, course, plan,
                                                               content.digest(cid), questions),
        "qcm_repair_prompt": lambda: prompts.qcm_repair_prompt(course, questions),
        "sheet_prompt": lambda: prompts.sheet_prompt(syl, course, plan,
                                                     content.substance(cid)),
        "syllabus_prompt": lambda: prompts.syllabus_prompt(syl, "series temporelles", 8),
        "daily_quiz_prompt": lambda: prompts.daily_quiz_prompt(
            syl, [{"course": course, "digest": content.digest(cid, limit=800), "seen": []}]),
        "refresher_prompt": lambda: prompts.refresher_prompt(
            syl, course, content.digest(cid, limit=800), [dict(questions[0], tries=2)],
            ["une question"]),
        "assistant_system": lambda: prompts.assistant_system("ÉTAT"),
        "question_system": lambda: prompts.question_system("CATALOGUE"),
        "course_import_prompt": lambda: prompts.course_import_prompt(syl, "/tmp/cours.pdf"),
        "code_change_system": lambda: prompts.code_change_system(),
        "code_change_prompt": lambda: prompts.code_change_prompt(
            "Sur la page d'accueil, ajouter un bouton « Exporter mes notes » qui écrit "
            "toutes les notes de cours dans un fichier Markdown choisi par l'utilisateur. "
            "Le bouton est désactivé tant qu'aucune note n'existe. " * 3),
        "code_fix_prompt": lambda: prompts.code_fix_prompt("ECHEC test x\nTraceback ..."),
        "chat_system": lambda: prompts.chat_system(course, syl),
        "proof_helper_system": lambda: prompts.proof_helper_system(course, syl),
        "proof_walkthrough_prompt": lambda: prompts.proof_walkthrough_prompt("T", "texte"),
        "proof_review_system (etape)": lambda: prompts.proof_review_system(course, syl, "etape"),
        "proof_review_system (complete)": lambda: prompts.proof_review_system(course, syl,
                                                                              "complete"),
        "proof_review_prompt": lambda: prompts.proof_review_prompt("T", "E", "S", "copie"),
        "td_structure_prompt": lambda: prompts.td_structure_prompt(syl, "/tmp/sujet.pdf"),
        "td_correction_prompt": lambda: prompts.td_correction_prompt(
            syl, "TD", {"number": "1", "title": "T", "statement": "<p>Énoncé</p>",
                        "courses": [cid], "key_results": ["un résultat"]},
            [{"course": course, "generated": True,
              "substance": content.substance(cid, limit=1500)}], 0, 3),
        "brouillon_prompt": lambda: prompts.brouillon_prompt(
            syl, course, "Théorème test", "Soit $f$ continue sur $[a,b]$.",
            "On pose $g(x) = f(x) - \\lambda x$ et on applique Rolle. " * 20),
        "training_prompt": lambda: prompts.training_prompt(
            syl, course, [s["title"] for s in plan["sections"]],
            content.substance(cid, limit=1500), ["un exercice déjà donné"]),
    }
    failed = []
    for name, build in builders.items():
        try:
            out = build()
            if not isinstance(out, str) or len(out) < 200:
                failed.append("%s: sortie vide" % name)
        except Exception as exc:  # noqa: BLE001
            failed.append("%s: %s: %s" % (name, type(exc).__name__, exc))
    check("chaque constructeur de prompt s'execute", not failed,
          "%d constructeurs%s" % (len(builders), (" — " + "; ".join(failed[:3])) if failed else ""))
    for schema in ("PLAN_SCHEMA", "EXERCISES_SCHEMA", "SYLLABUS_SCHEMA",
                   "QCM_REPAIR_SCHEMA", "DAILY_SCHEMA", "TD_SCHEMA", "TRAINING_SCHEMA",
                   "BROUILLON_SCHEMA"):
        check("  schema %s present" % schema, isinstance(getattr(prompts, schema, None), dict))


def test_td() -> None:
    """Sujets de TD : import, lecture normalisée, cache des corrections."""
    import tempfile
    from mathsapp import td as td_mod
    from mathsapp.generation import claude_cli as cc, pipeline
    from mathsapp.syllabus import load

    syl = load()
    # bibliotheque jetable : on ne touche pas aux TD reels
    previous = os.environ.get("MATHSAPP_LIBRARY")
    os.environ["MATHSAPP_LIBRARY"] = tempfile.mkdtemp(prefix="selftest-td-")
    try:
        sample = pathlib.Path(tempfile.mkdtemp()) / "sujet.pdf"
        sample.write_bytes(b"%PDF-1.4\n% selftest\n")
        td_id = td_mod.import_pdf(str(sample))
        check("import d'un sujet", td_mod.source_path(td_id).exists(), td_id)
        check("reimport du meme fichier sans doublon",
              td_mod.import_pdf(str(sample)) == td_id and len(td_mod.list_ids()) == 1)
        try:
            td_mod.import_pdf(str(sample.with_suffix(".txt")))
            refused = False
        except ValueError:
            refused = True
        check("un fichier non PDF est refuse", refused)

        raw = {"title": "TD", "exercises": [
            {"number": "1", "title": "A", "statement": "<p>Soit $x$.</p>",
             "courses": ["pro-esperance", "inexistant", "pro-esperance"], "difficulty": 9},
            {"number": "2", "title": "B", "statement": "   ", "courses": []},
            {"number": "3", "title": "", "statement": "<p>C</p>", "courses": ["pro-convergences"],
             "key_results": ["", "Borel-Cantelli"]}]}
        data = pipeline.normalize_td_structure(raw, syl)
        numbers = [e["number"] for e in data["exercises"]]
        check("lecture : enonce vide ecarte", numbers == ["1", "3"], str(numbers))
        check("lecture : cours inconnus et doublons retires",
              data["exercises"][0]["courses"] == ["pro-esperance"],
              str(data["exercises"][0]["courses"]))
        check("lecture : difficulte bornee", data["exercises"][0]["difficulty"] == 5)
        check("lecture : titre par defaut", data["exercises"][1]["title"] == "Exercice 3")

        td_mod.write_structure(td_id, data)
        first = data["exercises"][0]
        td_mod.write_correction(td_id, 0, td_mod.exercise_fingerprint(first),
                                "<h2>Corrigé</h2>" + "x" * 300)
        state = td_mod.state(td_id)
        check("etat : une correction sur deux", state["corrected"] == 1 and state["total"] == 2
              and not state["complete"], str(state))
        changed = dict(first, statement="<p>Autre énoncé</p>")
        check("cache invalide si l'enonce change",
              td_mod.read_correction(td_id, 0, td_mod.exercise_fingerprint(changed)) is None)

        mats = pipeline.td_materials(syl, {"courses": ["pro-espaces", "pro-convergences"]})
        check("matiere : un cours par rattachement", len(mats) == 2)
        cmd = cc._base_cmd("sonnet", None, False, tools="Read", add_dirs=["/tmp/x"])
        check("lecture du PDF : outil Read limite au dossier du TD",
              cmd[cmd.index("--tools") + 1] == "Read" and "/tmp/x" in cmd)
        default = cc._base_cmd("sonnet", None, False)
        check("par defaut, toujours aucun outil", default[default.index("--tools") + 1] == "")
    finally:
        if previous is None:
            os.environ.pop("MATHSAPP_LIBRARY", None)
        else:
            os.environ["MATHSAPP_LIBRARY"] = previous


def test_codex_backend() -> None:
    """Moteur codex : commande, sortie structuree, repli, chat, lecture des PDF."""
    import json as _json
    import tempfile
    from mathsapp import pdf_text
    from mathsapp.generation import claude_cli as cc, codex_cli as cx

    check("moteur par defaut : claude", cc.backend() in ("claude", "codex"))
    fake = pathlib.Path(tempfile.mkdtemp(prefix="selftest-codex-")) / "codex"
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    fake.chmod(0o755)
    exe = str(fake)
    check("codex : version", "faux" in cx.check_available(exe))

    seen = []
    res = cx.run_once("Un paragraphe.", "opus", system="Consigne.", exe=exe,
                      on_progress=seen.append)
    check("codex : texte final et progression", res.text == "<p>ok 0</p>" and seen and seen[-1] > 0,
          "%r %s" % (res.text, seen[-1:]))
    schema = {"type": "object", "properties": {"qcm": {"type": "array"}}}
    res = cx.run_once("QCM.", "sonnet", system="Consigne.", json_schema=schema, exe=exe)
    data = _json.loads(res.text)
    check("codex : sortie structuree, consignes en tete", data["qcm"] and data["vu"] is True)
    os.environ["FAKE_CODEX_REJECT"] = "--output-schema"
    try:
        res = cx.run_once("QCM.", "sonnet", json_schema=schema, exe=exe)
        check("codex : option refusee retiree, JSON redemande", _json.loads(res.text)["qcm"])
    finally:
        os.environ.pop("FAKE_CODEX_REJECT", None)
    pieces = []
    history = [{"role": "user", "content": "A ?"}, {"role": "assistant", "content": "a"},
               {"role": "user", "content": "B ?"}]
    res = cx.chat_stream("B ?", "opus", "S", None, pieces.append, history=history, exe=exe)
    check("codex : chat en fragments, historique renvoye sans doublon",
          res.text == "<p>ok 1</p>" and len(pieces) > 1, res.text)

    strict = cx.strict_schema({"type": "object", "properties": {
        "a": {"type": "string"},
        "b": {"type": "array", "items": {"type": "object", "properties": {"c": {"type": "integer"}},
                                         "required": []}}}})
    inner = strict["properties"]["b"]["items"]
    check("codex : schema ferme et tout requis",
          strict["required"] == ["a", "b"] and strict["additionalProperties"] is False
          and inner["required"] == ["c"] and inner["additionalProperties"] is False)
    check("codex : noms Claude traduits, autres gardes",
          cx.model_for("gpt-5-codex") == "gpt-5-codex"
          and cx.model_for("opus") == str(__import__("mathsapp.settings", fromlist=["x"]).get("codex/model_strong") or ""))
    cmd = ["codex", "exec", "--json", "--output-schema", "/s.json", "--cd", "/w", "p"]
    check("codex : retrait d'une option et de sa valeur",
          cx.drop_flag(cmd, "--output-schema") == ["codex", "exec", "--json", "--cd", "/w", "p"])
    check("codex : option refusee reconnue",
          cx.unsupported_flag(cmd, "error: unexpected argument '--output-schema'") == "--output-schema"
          and cx.unsupported_flag(cmd, "rate limit") is None)
    check("codex : raisonnement ignore",
          cx.message_text({"type": "item.completed", "item": {"type": "reasoning", "text": "x"}})
          == ("", False))
    check("pdf : plages de pages", pdf_text.page_range("5-18") == (5, 18)
          and pdf_text.page_range("42") == (42, 42) and pdf_text.page_range("") == (None, None))
    sample = next(iter(sorted((pathlib.Path(__file__).resolve().parent.parent / "library" / "_td")
                              .glob("*/source.pdf"))), None)
    if pdf_text.available() and sample is not None:
        text = pdf_text.extract(sample, "1-2")
        check("pdf : texte extrait par pdftotext", len(text) > 100, "%d caracteres" % len(text))


def test_course_import() -> None:
    """Cours importes : lecture nettoyee, plan avec source, rangement a part des TD."""
    import tempfile
    from mathsapp import content, course_import, td as td_mod
    from mathsapp.generation import pipeline, prompts
    from mathsapp.syllabus import load
    syl = load()

    raw = {"title": "", "level": 9, "prereqs": ["alg-espaces-vectoriels", "inexistant"],
           "related": ["opt-convexite", "zzz"], "keywords": ["a", "a", "b"],
           "sections": [
               {"title": "Espaces de Hilbert", "pages": "4-12", "goal": "g", "content": "c",
                "intuitions": ["norme induite"], "exercises": ["1", "9"]},
               {"title": "  ", "pages": "13", "goal": "", "content": ""},
               {"title": "Convexité", "pages": "13-30", "goal": "g", "content": "c",
                "exercises": ["2"]}],
           "exercises": [
               {"number": "1", "title": "", "statement": "<p>Soit $f$.</p>",
                "courses": ["opt-convexite", "inexistant"], "difficulty": 0},
               {"number": "2", "title": "Projection", "statement": "<p>Montrer.</p>"},
               {"number": "3", "title": "Vide", "statement": " "}]}
    data = course_import.normalize_import(raw, syl)
    check("import : titre par defaut", data["title"] == "Cours importé")
    check("import : niveau borne", data["level"] == 5)
    check("import : identifiants inconnus retires",
          "inexistant" not in data["prereqs"] and "zzz" not in data["related"],
          str((data["prereqs"], data["related"])))
    check("import : section sans titre ecartee, identifiants renumerotes",
          [s["id"] for s in data["sections"]] == ["s1", "s2"])
    check("import : exercice vide ecarte", [e["number"] for e in data["exercises"]] == ["1", "2"])
    check("import : renvoi vers un exercice inexistant ignore",
          data["sections"][0]["exercises"] == ["1"])
    check("import : doublons de mots-cles retires", data["keywords"] == ["a", "b"])
    entry = course_import.course_entry(dict(data, title="Rappels d'optimisation — partie I"))
    check("import : cours range dans le domaine des cours du MVA",
          entry["domain"] == course_import.DOMAIN["id"] and entry["id"].startswith("mva-"),
          entry["id"])

    previous = os.environ.get("MATHSAPP_LIBRARY")
    os.environ["MATHSAPP_LIBRARY"] = tempfile.mkdtemp(prefix="selftest-import-")
    try:
        folder = pathlib.Path(tempfile.mkdtemp())
        course_pdf = folder / "cours.pdf"
        course_pdf.write_bytes(b"%PDF-1.4\n% cours\n")
        td_pdf = folder / "td.pdf"
        td_pdf.write_bytes(b"%PDF-1.4\n% td\n")
        doc = course_import.import_pdf(str(course_pdf))
        td_id = td_mod.import_pdf(str(td_pdf))
        check("import : cours et TD ranges a part",
              course_import.list_ids() == [doc] and td_mod.list_ids() == [td_id],
              str((course_import.list_ids(), td_mod.list_ids())))
        check("import : meme fichier, meme document", course_import.import_pdf(str(course_pdf)) == doc)

        plan = course_import.build_plan(data, doc, syl)
        check("import : le plan garde la source et les pages",
              plan["source"]["pdf"].endswith("source.pdf") and plan["sections"][0]["pages"] == "4-12"
              and plan["sections"][0]["exercises"] == [{"number": "1", "title": "Exercice 1"}])
        tools = pipeline.source_tools(plan)
        check("import : chaque section relit son PDF, outil Read limite au dossier",
              tools.get("tools") == "Read" and tools["add_dirs"] == [str(td_mod.td_dir(doc))])
        check("cours ordinaire : aucun outil", pipeline.source_tools({"sections": []}) == {})
        course = syl.get("log-propositions")
        with_source = prompts.section_prompt(syl, course, plan, 0, [])
        plain = prompts.section_prompt(syl, course, dict(plan, source=None), 0, [])
        check("import : consignes de fidelite et exercices dans la section",
              "pages 4-12" in with_source and 'class="box exercise"' in with_source
              and "course-ref" in with_source and "SOURCE" not in plain)

        td_mod.write_structure(doc, {"title": "T", "exercises": data["exercises"]})
        first = data["exercises"][0]
        td_mod.write_correction(doc, 0, td_mod.exercise_fingerprint(first),
                                "<h2>Exercice 1 — titre</h2><p>Corrigé détaillé.</p>" + "x" * 200)
        body = course_import.exercises_body(doc)
        check("import : onglet Exercices",
              'id="exercice-1"' in body and "Corrigé détaillé" in body
              and "<h2>Exercice 1 — titre</h2>" not in body
              and "Correction pas encore produite" in body)
    finally:
        if previous is None:
            os.environ.pop("MATHSAPP_LIBRARY", None)
        else:
            os.environ["MATHSAPP_LIBRARY"] = previous


def test_questions() -> None:
    """Questions libres : catalogue, verification des liens, fils."""
    import html
    from mathsapp import content, questions, store
    from mathsapp.syllabus import load
    syl = load()

    ready = next((c.id for c in syl.all()
                  if content.is_complete(c.id) and questions.section_titles(c.id)), None)
    todo = next(c.id for c in syl.all() if not content.is_complete(c.id))
    cat = questions.catalogue(syl)
    check("questions : catalogue complet",
          todo in cat and (ready is None or questions.section_titles(ready)[0] in cat),
          "%d octets" % len(cat.encode("utf-8")))
    check("questions : catalogue assez court pour la ligne de commande",
          len(cat.encode("utf-8")) < 100000)
    if ready:
        title = questions.section_titles(ready)[0]
        src = ('<p>Voir <a class="course-ref" data-course="%s" data-section="%s">A</a>, '
               '<a class="course-ref" data-course="%s">B</a> et '
               '<a class="course-ref" data-course="inexistant">C</a> puis '
               '<a class="course-ref" data-course="%s" data-section="Section imaginaire">D</a>.</p>'
               % (ready, title.upper(), todo, ready))
        out = questions.link_courses(src, syl)
        check("questions : section retrouvee malgre la casse",
              'data-section="%s"' % html.escape(title, quote=True) in out, out[:240])
        check("questions : cours pas encore redige signale",
              'class="course-ref todo" data-course="%s"' % todo in out)
        check("questions : cours inconnu retire", "inexistant" not in out and " et C puis " in out)
        check("questions : section imaginaire ignoree", "Section imaginaire" not in out)
        check("questions : verification idempotente", questions.link_courses(out, syl) == out)
        check("questions : cours cites", questions.referenced_courses(out)[:2] == [ready, todo])

    thread = store.create_thread(None, questions.new_key(), "Nouvelle question")
    try:
        check("questions : fil vide non liste",
              all(r["id"] != thread for r in questions.threads()))
        store.add_message(thread, "user", "Qu'est-ce qu'une tribu ?")
        check("questions : fil liste des le premier message",
              any(r["id"] == thread for r in questions.threads()))
    finally:
        store.delete_thread(thread)
    check("questions : fil supprime", all(r["id"] != thread for r in questions.threads()))


def test_assistant() -> None:
    """Assistant : lecture des actions proposees, garde-fous, etat de l'app."""
    from mathsapp import assistant, status as st_mod
    from mathsapp.syllabus import load
    syl = load()
    from mathsapp import content
    # cours pris dans la bibliotheque du moment : elle evolue au fil des generations
    todo = [cid for cid in reversed(syl.topo) if not content.is_complete(cid)][:2]
    done = next(c.id for c in syl.all() if content.is_complete(c.id))

    text = ('<p>Voici.</p><actions>[{"type": "generate_courses", "courses": '
            '["%s", "%s", "inexistant", "%s"]},'
            '{"type": "set_setting", "key": "gen/section_parallel", "value": "4"},'
            '{"type": "set_setting", "key": "claude/binary", "value": "rm"},'
            '{"type": "set_setting", "key": "goal/bricks", "value": 99},'
            '{"type": "open", "page": "course", "course": "Chaînes de Markov"},'
            '{"type": "modify_app", "request": "court"},'
            '{"type": "inconnu"}]</actions>') % (todo[0], todo[1], done)
    visible, actions = assistant.parse_actions(text, syl)
    kinds = [a["type"] for a in actions]
    check("assistant : texte sans le bloc d'actions", visible == "<p>Voici.</p>", visible)
    check("assistant : actions invalides ecartees",
          kinds == ["generate_courses", "set_setting", "open"], str(kinds))
    gen = actions[0]
    check("assistant : cours inconnus et deja rediges ecartes",
          "inexistant" not in gen["courses"] and done not in gen["courses"]
          and sorted(gen["courses"]) == sorted(todo),
          str(gen["courses"]))
    rank = {cid: i for i, cid in enumerate(syl.topo)}
    check("assistant : cours ranges dans l'ordre des prerequis",
          gen["courses"] == sorted(gen["courses"], key=rank.get), str(gen["courses"]))
    check("assistant : reglage converti", actions[1]["value"] == 4)
    check("assistant : cours retrouve par son titre", actions[2]["course"] == "pro-markov")
    check("assistant : bloc non termine masque",
          assistant.split_answer("ok <actions>[{\"type\"")[0] == "ok")
    check("assistant : JSON illisible sans action",
          assistant.parse_actions("<p>a</p><actions>pas du json</actions>", syl)
          == ("<p>a</p>", []))
    check("assistant : flux coupe avant le bloc",
          [assistant.visible_limit(s) for s in ("abc", "abc<act", "abc<actions>[", "a<b")]
          == [3, 3, 3, 3])
    subject = assistant._subject("Dans la page TD, renommer le bouton « Énoncé seul » en « Masquer la correction »")
    check("assistant : titre de commit coupe a un mot entier",
          len(subject) <= 69 and subject.endswith("…") and "Énonc…" not in subject, subject)
    state = assistant.app_state(syl, st_mod.compute(syl))
    check("assistant : etat complet",
          "pro-markov" in state and "RÉGLAGES MODIFIABLES" in state and "TD IMPORTÉS" in state,
          "%d caracteres" % len(state))
    check("assistant : etat assez court pour la ligne de commande",
          len(state.encode("utf-8")) < 100000, "%d octets" % len(state.encode("utf-8")))

    import time as _time
    from types import SimpleNamespace
    from mathsapp.chat import ChatSession
    from mathsapp.generation.queue import CANCELLED, QUEUED, RUNNING, Job
    statuses = st_mod.compute(syl)
    empty = assistant.queue_state(syl, statuses, [], limit=2)
    check("assistant : file vide signalee", "file vide" in empty, empty.splitlines()[1])
    now = _time.time()
    jobs = [Job(course_id="x%d" % i, title="X%d" % i, state=QUEUED) for i in range(20)]
    jobs[0].state = jobs[1].state = RUNNING
    jobs.append(Job(course_id="annule", title="Annulé", state=CANCELLED, finished_at=now - 60))
    jobs.append(Job(course_id="ancien", title="Ancien", state=CANCELLED, finished_at=now - 7200))
    text = assistant.queue_state(syl, statuses, jobs, now=now, limit=2)
    check("assistant : file longue tronquee",
          "et 6 autres éléments" in text and text.count("\n- [") == assistant.QUEUE_MAX_ITEMS,
          text.splitlines()[-1])
    check("assistant : raison de l'attente donnee", "limite gen/concurrency atteinte (2/2" in text)
    short = assistant.queue_state(syl, statuses, jobs[:2] + jobs[-2:], now=now, limit=2)
    check("assistant : annulation recente signalee, ancienne omise",
          "annule (Annulé) : annulé" in short and "ancien" not in short, short)
    fake = SimpleNamespace(mode="assistant", queue_provider=lambda: "FILE DE GÉNÉRATION\n- x")
    sent = ChatSession.turn_prompt(fake, "Pourquoi en pause ?")
    check("assistant : etat joint a chaque message",
          "FILE DE GÉNÉRATION" in sent and sent.endswith("Pourquoi en pause ?"), sent)
    fake.mode = "general"
    check("discussion ordinaire : message intact",
          ChatSession.turn_prompt(fake, "salut") == "salut")

    # cartes d'action : enregistrees avec leur message, etat propre a chacune
    from mathsapp import store
    tid = store.create_thread(None, "selftest-actions", "test")
    try:
        cards = [{"id": "st-a1", "type": "open", "page": "graph", "label": "A"},
                 {"id": "st-a2", "type": "open", "page": "course", "course": "pro-markov",
                  "label": "B"},
                 {"id": "st-a3", "type": "modify_app", "request": "x" * 12, "label": "C"}]
        first_msg = store.add_message(tid, "assistant", "<p>un</p>")
        store.add_chat_actions(tid, first_msg, cards[:2])
        for i in range(60):   # conversation longue : les cartes anciennes restent
            store.add_message(tid, "user" if i % 2 else "assistant", "m%d" % i)
        last_msg = store.add_message(tid, "assistant", "<p>deux</p>")
        store.add_chat_actions(tid, last_msg, cards[2:])
        store.set_chat_action_state("st-a1", "done", "ouvert")
        saved = store.chat_actions(tid)
        check("assistant : cartes rattachees a leur message",
              [c["id"] for c in saved.get(first_msg, [])] == ["st-a1", "st-a2"]
              and [c["id"] for c in saved.get(last_msg, [])] == ["st-a3"], str(saved)[:200])
        check("assistant : etat independant pour chaque carte d'un message",
              [c["state"] for c in saved[first_msg]] == ["done", "proposed"])
        check("assistant : carte relue avec son action",
              (store.chat_action("st-a2") or {}).get("course") == "pro-markov")
        check("assistant : carte faite non relancable",
              "done" not in assistant.CARD_CLICKABLE and "ignored" not in assistant.CARD_CLICKABLE
              and "waiting" not in assistant.CARD_CLICKABLE)
        store.set_chat_action_state("st-a3", "running", "en cours…")
        check("assistant : chantier interrompu par un redemarrage, carte relancable",
              assistant.settle_card(store.chat_action("st-a3"))[0] == "failed"
              and assistant.settle_card(store.chat_action("st-a3"), {"st-a3"})[0] == "running")
        check("assistant : attente interrompue, carte de nouveau proposee",
              assistant.settle_card({"id": "z", "state": "waiting"})[0] == "proposed")
        check("assistant : cours devenu invalide explique",
              "introuvable" in assistant.action_problem(
                  {"type": "generate_courses", "courses": ["cours-disparu"]}, syl)
              and assistant.action_problem(cards[1], syl) == "")
    finally:
        store.delete_thread(tid)
    check("assistant : cartes effacees avec le fil", store.chat_action("st-a1") is None)


def test_math_lt() -> None:
    """Un « < » de formule ne doit jamais etre pris pour une balise."""
    from mathsapp import content
    p = content.protect_math
    check("somme sur i<j", p(r"<p>$\sum_{i<j} x_i$</p>") == r"<p>$\sum_{i&lt;j} x_i$</p>")
    check("suite croissante", "u_{n+1}&lt;u_n" in p(r"<li>($u_{n+1}<u_n$ pour tout $n$)</li>"))
    check("formule en display", "x&lt;y" in p(r"<p>$$x<y$$</p>"))
    check("indice suivi d'un espace", r"k&lt;i \le n" in p(r"<em>$k<i \le n$</em>"))
    check("vraies balises intactes", p('<p>$a$ <b>gras</b> et $c$ <a class="x" href="#">lien</a></p>')
          == '<p>$a$ <b>gras</b> et $c$ <a class="x" href="#">lien</a></p>')
    check("script intact", p("<script>if (a<b) { f('$x$') }</script>")
          == "<script>if (a<b) { f('$x$') }</script>")
    check("texte sans formule intact", p("<p>a < b</p>") == "<p>a < b</p>")
    data = content.protect_math_data({"qcm": [{"choices": [r"$i<k$", "rien"], "answer": 1}]})
    check("questions JSON traitees", data["qcm"][0]["choices"] == [r"$i&lt;k$", "rien"]
          and data["qcm"][0]["answer"] == 1)


def test_refresher() -> None:
    """Quiz du jour resserre et rappels cibles."""
    import inspect
    import tempfile
    from mathsapp import content, review
    from mathsapp.generation import pipeline

    check("quiz du jour : dix questions par defaut",
          inspect.signature(pipeline.generate_daily_quiz).parameters["count"].default == 10)
    check("quiz du jour : quatre cours au plus",
          inspect.signature(pipeline.pick_daily_courses).parameters["count"].default == 4)
    check("rappel : pas sur une seule erreur", not review.needs_refresher(10, 1, 1))
    check("rappel : pas avec trop peu de reponses", not review.needs_refresher(3, 2, 2))
    check("rappel : erreurs frequentes", review.needs_refresher(8, 3, 0))
    check("rappel : erreurs repetees", review.needs_refresher(20, 2, 2))
    check("rappel : erreurs rares et isolees", not review.needs_refresher(20, 3, 0))

    previous = os.environ.get("MATHSAPP_LIBRARY")
    os.environ["MATHSAPP_LIBRARY"] = tempfile.mkdtemp(prefix="selftest-rappel-")
    try:
        day = "2026-09-14"
        content.write_refresher(day, "pro-espaces", {"qcm": [{"id": "r1", "question": "Q"}]})
        check("rappel : retrouve par jour", content.pending_refresher(day) == "pro-espaces")
        check("rappel : questions indexees",
              ("pro-espaces", "rappel", "r1") in content.question_index())
        content.mark_refresher_done(day, "pro-espaces")
        check("rappel : fait, plus propose", content.pending_refresher(day) is None)
        check("rappel : liste", content.refreshers() == [(day, "pro-espaces")])
    finally:
        if previous is None:
            os.environ.pop("MATHSAPP_LIBRARY", None)
        else:
            os.environ["MATHSAPP_LIBRARY"] = previous
    check("rappel : detection sur les vraies donnees sans erreur",
          isinstance(review.refresher_candidates(), list))


def test_store() -> None:
    from mathsapp import status as st_mod, store
    from mathsapp.syllabus import load
    syl = load()
    statuses = st_mod.compute(syl)
    check("statuts calcules", len(statuses) == len(syl.courses))
    first = syl.topo[0]
    check("premier cours accessible", statuses[first].unlocked, first)
    tid = store.create_thread(None, "selftest", "test")
    store.add_message(tid, "user", "coucou")
    check("fil de discussion persiste", len(store.messages(tid)) == 1)
    store.clear_thread(tid)


def test_training() -> None:
    """TD d'entrainement : normalisation, ecriture d'un bloc, version du cours, rendu."""
    import tempfile
    from mathsapp import content, store, training
    from mathsapp.generation import pipeline, queue as queue_mod
    from mathsapp.syllabus import load

    check("TD d'entrainement : libelle distinct des TD importes",
          queue_mod.kind_label("training") != queue_mod.kind_label("td")
          and "TD 2" in queue_mod.kind_label("training:2"))
    store.conn()   # la base reste celle deja ouverte, pas celle du dossier temporaire
    previous = os.environ.get("MATHSAPP_LIBRARY")
    os.environ["MATHSAPP_LIBRARY"] = tempfile.mkdtemp(prefix="selftest-entrainement-")
    try:
        syl = load()
        try:
            pipeline.generate_training(syl.topo[0], syl=syl)
            refused = ""
        except ValueError as exc:
            refused = str(exc)
        check("TD refuse pour un cours non redige, sans appel au modele", "rédigé" in refused,
              refused)

        cid = "selftest-entrainement"
        body = "<h2>Suites</h2>" + "<p>texte du cours</p>" * 30
        content.write_body(cid, body)
        content.write_json(cid, content.META, {"generated_at": 1000.0})
        raw = {"exercises": [
            {"level": "Approfondissement", "title": "C", "statement": "<p>c</p>",
             "hints": ["h1", "h2", "h3"], "solution": "<p>s</p>", "section": "suites"},
            {"level": "application directe", "title": "A", "statement": "<p>a</p>",
             "hints": [], "solution": "<p>s</p>", "section": "Inconnue"},
            {"level": "classique", "title": "B", "statement": "", "hints": [],
             "solution": "<p>s</p>", "section": ""},
        ]}
        items = training.normalize_exercises(raw, ["Suites"])
        check("normalisation : enonce vide ecarte, difficulte croissante",
              [e["title"] for e in items] == ["A", "C"]
              and [e["id"] for e in items] == ["e1", "e2"])
        check("normalisation : deux indices au plus, section verifiee",
              len(items[1]["hints"]) == 2 and items[1]["section"] == "Suites"
              and items[0]["section"] == "")
        first = training.save(cid, items, cost_usd=0.3, duration_s=120.0)
        second = training.save(cid, items)
        check("plusieurs TD numerotes", (first, second) == (1, 2)
              and len(training.list_tds(cid)) == 2)
        check("ecriture d'un bloc : aucun fichier temporaire",
              not list(training.training_dir(cid).glob("*.tmp")))
        check("TD a jour du cours", not training.is_outdated(training.read_td(cid, 1), cid))

        content.delete_course(cid)          # comme au debut d'une regeneration
        content.write_body(cid, body)
        content.write_json(cid, content.META, {"generated_at": 2000.0})
        check("TD conserve apres regeneration du cours", len(training.list_tds(cid)) == 2)
        check("TD signale comme ecrit pour une version anterieure",
              training.is_outdated(training.read_td(cid, 1), cid))

        page = training.page_body(cid, {"1/e1": "ok"})
        check("rendu : indices et corrige replies, lien de section, statut, avertissement",
              '<details class="training-solution">' in page and "<details open" not in page
              and 'data-section="Suites"' in page
              and 'data-key="1/e1" data-status="ok" class="on"' in page
              and "version antérieure" in page)
        check("estimation tiree des feuilles produites", training.estimate() == (120.0, 0.3))
        check("suppression d'un TD", training.delete(cid, 2)
              and [t["id"] for t in training.list_tds(cid)] == [1])
        empty = training.page_body("selftest-sans-td", {})
        check("rendu sans feuille : invitation a generer", "Générer un TD" in empty)
    finally:
        store.clear_training_status("selftest-entrainement", "1")
        if previous is None:
            os.environ.pop("MATHSAPP_LIBRARY", None)
        else:
            os.environ["MATHSAPP_LIBRARY"] = previous


def test_brouillon() -> None:
    """Brouillons des demonstrations : cles stables, obsolescence, page, bascule."""
    import tempfile
    from mathsapp import assistant, brouillon, content, settings as settings_mod
    from mathsapp.generation import pipeline, queue as queue_mod
    from mathsapp.syllabus import load
    from mathsapp.ui.webview import WebView

    check("brouillon : reglage gen/auto_brouillon, desactive par defaut",
          settings_mod.DEFAULTS.get("gen/auto_brouillon") is False
          and "gen/auto_brouillon" in assistant.SETTINGS_ALLOWED)
    action = assistant.normalize_action(
        {"type": "set_setting", "key": "gen/auto_brouillon", "value": "oui"}, load())
    check("brouillon : reglage modifiable par l'assistant",
          bool(action) and action["value"] is True)
    check("brouillon : libelle dans la file",
          queue_mod.kind_label("brouillon:c-x") == "Brouillon d'une démonstration"
          and queue_mod.kind_label("brouillon") == "Brouillons des démonstrations")

    long_proof = "<p>On pose $g(x) = f(x) - \\lambda x$, puis on applique Rolle.</p>" * 6
    def body_with(proof: str) -> str:
        return ('<h2>Accroissements</h2>'
                '<div class="box theorem"><span class="box-title">Théorème</span>'
                '<p class="statement">Soit $f$ continue sur $[a,b]$.</p></div>'
                '<details class="proof" data-of="Théorème des accroissements finis">'
                '<summary>Démonstration</summary><div class="proof-body">%s</div></details>'
                '<p>Suite du cours, assez longue pour un vrai corps de cours.</p>'
                '<details class="proof" data-of="Lemme court"><summary>Démonstration</summary>'
                '<div class="proof-body"><p>Immédiat.</p></div></details>'
                '<details class="proof" data-of="Lemme court"><summary>Démonstration</summary>'
                '<div class="proof-body"><p>Idem.</p></div></details>' % proof)

    previous = os.environ.get("MATHSAPP_LIBRARY")
    os.environ["MATHSAPP_LIBRARY"] = tempfile.mkdtemp(prefix="selftest-brouillon-")
    try:
        syl = load()
        cid = syl.topo[0]
        content.write_body(cid, body_with(long_proof))
        content.write_json(cid, content.EXOS, {"qcm": [], "proofs": [
            {"id": "d1", "title": "Exercice", "statement": "<p>Montrer que…</p>",
             "solution": "<p>%s</p>" % ("Raisonnons par récurrence forte. " * 12),
             "steps": [], "hints": []}]})
        entries = brouillon.proofs(cid)
        keys = [e["key"] for e in entries]
        check("cles stables tirees du nom du resultat",
              keys == ["c-theoreme-des-accroissements-finis", "c-lemme-court",
                       "c-lemme-court-2", "d-d1"], str(keys))
        check("enonce retrouve avant la preuve", "continue" in entries[0]["statement"])
        check("preuve d'une ligne : pas de brouillon propose",
              entries[0]["eligible"] and not entries[1]["eligible"] and entries[3]["eligible"])
        annotated = brouillon.annotate(content.read_body(cid))
        check("demonstrations du cours marquees de leur cle",
              'data-of="Théorème des accroissements finis" '
              'data-brouillon="c-theoreme-des-accroissements-finis">' in annotated
              and annotated.count("data-brouillon=") == 3)
        check("a produire : les seules preuves qui le meritent",
              [e["key"] for e in brouillon.pending(cid)]
              == ["c-theoreme-des-accroissements-finis", "d-d1"])
        brouillon.save(cid, entries[0], "<h4>Point de départ</h4><p>Idée $x$.</p>", False)
        state = brouillon.state_map(cid)
        check("brouillon enregistre, a jour",
              state["c-theoreme-des-accroissements-finis"]["status"] == "ok"
              and [e["key"] for e in brouillon.pending(cid)] == ["d-d1"])

        content.delete_course(cid)          # regeneration : la preuve change
        content.write_body(cid, body_with(long_proof.replace("Rolle", "le TAF")))
        state = brouillon.state_map(cid)
        check("brouillon conserve et marque obsolete quand la preuve change",
              state["c-theoreme-des-accroissements-finis"]["status"] == "obsolete"
              and "Idée" in state["c-theoreme-des-accroissements-finis"]["html"])
        try:
            pipeline.generate_brouillons(cid, ["c-inconnue"], syl=syl)
            refused = ""
        except ValueError as exc:
            refused = str(exc)
        check("demonstration disparue : erreur claire, sans appel au modele",
              "introuvable" in refused, refused)

        # la page de cours : bascule preuve / brouillon, formules rendues
        page = brouillon.inject(content.build_page(annotated, "Selftest", "light"), cid)
        check("etat des brouillons joint a la page", "window.BROUILLONS" in page)
        path = pathlib.Path(tempfile.mkdtemp()) / "brouillon.html"
        path.write_text(page, encoding="utf-8")
        view = WebView(with_bridge=True)
        view.resize(900, 700)
        view.show()
        loaded: dict = {}
        view.loadFinished.connect(lambda ok: loaded.update(ok=ok))
        view.load_file(path)
        wait_until(lambda: "ok" in loaded)
        wait(1500)
        def js(code: str):
            box: dict = {}
            view.page().runJavaScript(code, lambda r: box.update(r=r))
            wait_until(lambda: "r" in box, 8000)
            return box.get("r")

        switches = js("document.querySelectorAll('.proof-switch').length")
        check("bascule sur les seules preuves qui meritent un brouillon",
              switches == 1, str(switches))
        # les erreurs levees dans un gestionnaire de clic ne remontent pas a
        # click() : on les capte pour que l'echec dise ce qui s'est passe
        js("window.__errs = []; window.addEventListener('error', function (e) {"
           " window.__errs.push(String(e.message)); });"
           "var d = document.querySelector('details[data-brouillon]'); d.open = true;"
           "try { d.querySelectorAll('.proof-switch button')[1].click(); }"
           "catch (e) { window.__errs.push(String(e)); } true;")
        wait(300)
        raw = js("(function(){ try {"
                 " var d = document.querySelector('details[data-brouillon]');"
                 " var p = d.querySelector('.brouillon-pane');"
                 " return JSON.stringify({katex: !!p && !!p.querySelector('.katex'),"
                 "  display: d.querySelector('.proof-body').style.display,"
                 "  obsolete: !!p && p.textContent.indexOf('Obsolète') >= 0,"
                 "  errors: window.__errs || []});"
                 " } catch (e) { return JSON.stringify({errors: [String(e)]}); } })()")
        import json as _json
        toggle = _json.loads(raw) if isinstance(raw, str) else {"errors": [repr(raw)]}
        check("brouillon affiche a la place de la preuve, formules rendues, obsolete signale",
              toggle.get("katex") is True and toggle.get("display") == "none"
              and toggle.get("obsolete") is True, str(toggle))
        view.deleteLater()
    finally:
        if previous is None:
            os.environ.pop("MATHSAPP_LIBRARY", None)
        else:
            os.environ["MATHSAPP_LIBRARY"] = previous


def test_pages() -> None:
    from mathsapp import content
    page = content.build_page("<h2>Test $x^2$</h2>", "Test", "light")
    ok = ("katex.min.css" in page and "mviz.js" in page and "<h2>Test $x^2$</h2>" in page
          and "__ASSETS__" not in page and "__BODY__" not in page)
    check("assemblage de la page de cours", ok)
    cleaned = content.clean_html("```html\n<h2>A</h2>\n```")
    check("nettoyage des reponses du modele", cleaned == "<h2>A</h2>", repr(cleaned))


def test_qcm_balance() -> None:
    """La bonne reponse ne doit pas se reconnaitre a sa forme."""
    import collections
    import statistics
    from mathsapp import content
    from mathsapp.generation import pipeline
    from mathsapp.syllabus import load

    qcm = [{"id": "q%d" % i, "choices": ["a", "b", "c", "d"], "answer": 0}
           for i in range(16)]
    pipeline.rebalance_positions(qcm, seed=3)
    spread = collections.Counter(q["answer"] for q in qcm)
    check("positions reparties sur les quatre reponses",
          len(spread) == 4 and max(spread.values()) <= 6, dict(sorted(spread.items())))

    positional = {"id": "p", "answer": 0,
                  "choices": ["aucune de ces réponses", "b", "c", "d"]}
    pipeline.rebalance_positions([positional], seed=1)
    check("propositions renvoyant aux autres non permutees",
          positional["answer"] == 0 and positional["choices"][0].startswith("aucune"))

    biased = {"id": "b", "answer": 2, "choices": [
        "Faux.", "Non.",
        "Vrai, car la suite est croissante et majorée donc convergente vers sa "
        "borne supérieure, ce qui conclut immédiatement.", "Peut-être."]}
    balanced = {"id": "e", "answer": 1, "choices": [
        "La suite diverge.", "La suite converge.", "La suite est bornée.",
        "La suite est constante."]}
    offenders = [q["id"] for q in pipeline.length_offenders([biased, balanced])]
    check("desequilibre de longueur detecte", offenders == ["b"], str(offenders))

    # sur les exercices reellement produits
    syl = load()
    allq = []
    for course in syl.all():
        data = content.read_exercises(course.id)
        if data:
            allq.extend(data.get("qcm") or [])
    if not allq:
        return
    spread = collections.Counter(q["answer"] for q in allq)
    worst = max(spread.values()) / len(allq)
    check("QCM produits : aucune position dominante", worst < 0.40,
          "%s, position la plus frequente %.0f %%" % (dict(sorted(spread.items())), 100 * worst))
    longest = 0
    for q in allq:
        lengths = [len(pipeline._plain(c)) for c in q["choices"]]
        if lengths[q["answer"]] == max(lengths):
            longest += 1
    check("QCM produits : la bonne reponse n'est pas la plus longue",
          longest / len(allq) < 0.45,
          "%d / %d (%.0f %%)" % (longest, len(allq), 100 * longest / len(allq)))


def test_section_context() -> None:
    """Chaque section doit savoir ce que les autres traitent deja."""
    from mathsapp import content
    from mathsapp.generation import prompts
    from mathsapp.syllabus import load

    syl = load()
    cid = next((c.id for c in syl.all() if content.has_course(c.id)), None)
    if cid is None:
        return
    plan = content.read_plan(cid)
    if not plan:
        return
    section_dir = content.sections_dir(cid)
    written = sorted(section_dir.glob("*.html"))
    if len(written) < 3:
        return
    body = written[1].read_text(encoding="utf-8")
    items = content.section_items(body)
    check("notions d'une section extraites", len(items) >= 3, "%d notions" % len(items))

    covered = "\n".join("  - %s" % it for it in items)
    upcoming = "  5. Suite — contenu prevu"
    prompt = prompts.section_prompt(syl, syl.get(cid), plan, 3,
                                    [s["title"] for s in plan["sections"][:3]],
                                    covered, upcoming)
    check("prompt : notions deja vues transmises",
          "DEJA INTRODUIT" in prompt and items[0][:30] in prompt)
    check("prompt : contenus a venir signales",
          "TRAITE AILLEURS" in prompt and "contenu prevu" in prompt)
    check("prompt : le plan donne le contenu, pas seulement les titres",
          plan["sections"][0].get("content", "zzz")[:40] in prompt)


def test_quiz_sets() -> None:
    """Series multiples, suivi par question, sessions partielles."""
    from mathsapp import content, store
    from mathsapp.generation import pipeline
    from mathsapp.syllabus import load

    syl = load()
    cid = next((c.id for c in syl.all() if content.has_exercises(c.id)), None)
    if cid is None:
        return
    sets = content.quiz_sets(cid)
    check("serie 1 issue des exercices du cours",
          sets and sets[0]["id"] == "1" and len(sets[0]["qcm"]) > 0,
          "%d serie(s)" % len(sets))
    check("identifiants de question uniques",
          len({q["id"] for q in content.all_questions(cid)})
          == len(content.all_questions(cid)))

    # suivi par question, sans polluer les scores du cours ni l'historique reel
    # copie brute de toutes les colonnes : echeances et intervalles compris
    saved = [dict(r) for r in store.conn().execute(
        "SELECT * FROM question_result WHERE course_id=?", (cid,))]
    before = len(store.attempts(cid))
    qs = sets[0]["qcm"][:3]
    try:
        store.reset_question_history(cid)
        detail = {"answers": [{"id": q["id"], "ok": i != 1} for i, q in enumerate(qs)]}
        store.record_attempt(cid, 3, 2, detail, set_id="1", partial=True)
        history = store.question_history(cid).get("1", {})
        check("resultat par question enregistre",
              all(q["id"] in history for q in qs), "%d suivis" % len(history))
        check("session partielle ne compte pas comme un score du cours",
              len(store.attempts(cid)) == before)
        mine = {q["id"] for q in qs}
        ko = sorted(qid for qid, h in history.items()
                    if qid in mine and not h["ok"])
        check("questions ratees identifiables", ko == [qs[1]["id"]], str(ko))
    finally:
        store.reset_question_history(cid)
        for row in saved:
            store.conn().execute(
                "INSERT OR REPLACE INTO question_result (%s) VALUES (%s)"
                % (", ".join(row), ", ".join("?" * len(row))), tuple(row.values()))
        store.conn().commit()
        restored = [dict(r) for r in store.conn().execute(
            "SELECT * FROM question_result WHERE course_id=?", (cid,))]
        key = lambda r: (r["set_id"], r["question_id"])
        check("historique reel restaure a l'identique",
              sorted(restored, key=key) == sorted(saved, key=key))

    # requalification des faux exercices
    batch = [
        {"kind": "exercice", "difficulty": 2, "question": "<p>Calculez.</p>"},
        {"kind": "exercice", "difficulty": 4, "question": "<p>" + "x" * 260 + "</p>"},
        {"kind": "direct", "difficulty": 5, "question": "<p>court</p>"},
    ]
    moved = pipeline.retag_exercises(batch)
    check("faux exercices requalifies",
          moved == 1 and [q["kind"] for q in batch] == ["direct", "exercice", "direct"],
          str([q["kind"] for q in batch]))


def test_gamify() -> None:
    """Revisions espacees, objectif, serie, XP, niveaux, jalons."""
    from mathsapp import content, gamify, review as review_mod, status as st_mod, store
    from mathsapp.syllabus import load

    # --- planification
    interval, ease, due = review_mod.schedule(True, None, None, now=0.0)
    check("premiere reussite : revision a un jour",
          interval == 1.0 and due == review_mod.DAY, "%.1f j" % interval)
    steps = []
    i, e = interval, ease
    for _ in range(4):
        i, e, _d = review_mod.schedule(True, i, e)
        steps.append(round(i, 1))
    check("les intervalles s'allongent", steps == sorted(steps) and steps[-1] > 20,
          str(steps))
    i2, e2, due2 = review_mod.schedule(False, i, e, now=1000.0)
    check("un echec ramene la question tout de suite",
          i2 == 0.0 and due2 == 1000.0 and e2 < e, "%.1f j, facilite %.2f" % (i2, e2))

    # --- journal, objectif, serie : sur des jours factices
    fake = ["1999-12-29", "1999-12-30", "1999-12-31", "2000-01-01"]
    c = store.conn()
    try:
        for day in fake:
            c.execute("DELETE FROM day_log WHERE day=?", (day,))
        c.execute("DELETE FROM xp_event WHERE day IN ('%s')" % "','".join(fake))
        c.commit()

        gamify.log("test", questions=10, correct=8, brick=True, xp=42,
                   domain="logique", day=fake[0])
        row = gamify.day_row(fake[0])
        check("journal du jour", row["questions"] == 10 and row["bricks"] == 1
              and row["xp"] == 42, str({k: row[k] for k in ("questions", "bricks", "xp")}))

        before = gamify.xp_total()
        gamify.log("test", xp=8, domain="logique", day=fake[1])
        check("XP cumulee", gamify.xp_total() == before + 8)
        check("XP par domaine", gamify.xp_by_domain().get("logique", 0) >= 50)

        for day in fake:
            c.execute("DELETE FROM day_log WHERE day=?", (day,))
        c.execute("DELETE FROM xp_event WHERE day IN ('%s')" % "','".join(fake))
        c.commit()
    finally:
        pass

    # --- niveaux
    check("niveau 1 au depart", gamify.level_of(0)[0] == 1)
    levels = [gamify.level_of(x)[0] for x in (0, 100, 270, 510, 5000)]
    check("les niveaux montent", levels == sorted(levels) and levels[-1] > 5, str(levels))

    # --- XP d'une question selon la difficulte et le type
    easy = gamify.question_xp(1, True)
    hard = gamify.question_xp(5, True)
    exo = gamify.question_xp(5, True, "exercice")
    wrong = gamify.question_xp(5, False)
    check("une question difficile rapporte plus", hard > easy and exo > hard,
          "%d < %d < %d" % (easy, hard, exo))
    check("se tromper rapporte quand meme un peu", 0 < wrong < easy, str(wrong))

    # --- serie : un gel couvre un oubli recent, pas un trou ancien
    import datetime as _dt
    today_d = _dt.date.today()
    days = {(today_d - _dt.timedelta(days=n)).isoformat(): n for n in range(6)}
    saved = {d: gamify.day_row(d) for d in days}
    try:
        for d in days:
            c.execute("DELETE FROM day_log WHERE day=?", (d,))
        c.commit()
        # travaille aujourd'hui, avant-hier, et il y a 5 jours
        for n in (0, 2, 5):
            gamify.log("test", brick=True, day=(today_d - _dt.timedelta(days=n)).isoformat())
        streak = gamify.refresh_streak()
        check("la serie couvre l'oubli d'hier", streak.current == 3,
              "%d jours" % streak.current)
        check("un gel a ete consomme", streak.freezes_left < gamify.FREEZES_PER_MONTH,
              "%d gels restants" % streak.freezes_left)
        check("le trou de 3-4 jours n'est pas couvert", streak.current < 6)
    finally:
        for d in days:
            c.execute("DELETE FROM day_log WHERE day=?", (d,))
        for d, row in saved.items():
            if row["bricks"] or row["questions"] or row["xp"]:
                c.execute(
                    "INSERT OR REPLACE INTO day_log "
                    "(day, bricks, questions, correct, proofs, reviews, seconds, xp, frozen) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (d, row["bricks"], row["questions"], row["correct"], row["proofs"],
                     row["reviews"], row["seconds"], row["xp"], row["frozen"]))
        c.commit()

    # --- jalons
    syl = load()
    statuses = st_mod.compute(syl)
    ctx = gamify.build_context(syl, statuses)
    check("contexte des jalons complet",
          all(k in ctx for k in ("correct_total", "proofs_done", "streak", "level")))
    ids = [m.id for m in gamify.MILESTONES]
    check("jalons sans doublon d'identifiant", len(ids) == len(set(ids)))
    broken = []
    for milestone in gamify.MILESTONES:
        try:
            milestone.reach(ctx)
            if milestone.progress:
                milestone.progress(ctx)
        except Exception as exc:  # noqa: BLE001
            broken.append("%s: %s" % (milestone.id, exc))
    check("tous les jalons s'evaluent", not broken, str(broken[:2]))

    # --- quiz du jour et resolution des questions
    index = content.question_index()
    check("index des questions construit", len(index) > 50, "%d questions" % len(index))
    days_available = content.daily_days()
    if days_available:
        data = content.read_daily(days_available[-1])
        qcm = data.get("qcm", [])
        check("quiz du jour : questions rattachees a un cours",
              all(q.get("course_id") in syl.courses for q in qcm),
              str({q.get("course_id") for q in qcm} - set(syl.courses)))
        check("quiz du jour : plusieurs cours",
              len({q["course_id"] for q in qcm}) >= 3,
              "%d cours" % len({q["course_id"] for q in qcm}))
        check("quiz du jour : questions retrouvables",
              all(("", "daily", q["id"]) in index or (q["course_id"], "daily", q["id"]) in index
                  for q in qcm[:5]))


def test_review_modes() -> None:
    """Deux registres de relecture : travail en cours et copie terminee."""
    from mathsapp.chat import ChatSession
    from mathsapp.generation import prompts

    etape = prompts.proof_review_system(None, None, "etape")
    complete = prompts.proof_review_system(None, None, "complete")
    check("mode etape : pas de verdict",
          "Pas de verdict" in etape and "Ne relevez donc jamais" in etape)
    check("mode etape : ne reproche pas l'inachevement",
          "ne prétend pas avoir fini" in etape)
    check("mode complet : ouvre sur l'acquis",
          complete.index("Ce qui est acquis") < complete.index("Le point à reprendre"))
    for text, label in ((etape, "etape"), (complete, "complete")):
        check("  %s : tournures decourageantes bannies" % label,
              "il suffit de" in text and "vous auriez dû" in text)
        check("  %s : exactitude preservee" % label,
              "Une affirmation fausse est dite" in text)
    check("un seul point a la fois",
          "Une seule chose à reprendre à la fois" in etape)

    session = ChatSession(None, None, "selftest-review", "review-etape")
    check("session en mode etape", "SUIS-JE SUR LA BONNE VOIE" in session.system)
    session2 = ChatSession(None, None, "selftest-review2", "review")
    check("session en mode complet", "CORRECTION COMPLÈTE" in session2.system)
    prompt = prompts.proof_review_prompt("T", "E", "S", "debut", 2, "etape")
    check("relance : progression mentionnee d'abord",
          "ce qui a progressé" in prompt and "bonne voie" in prompt)


def test_score_updates() -> None:
    """Refaire une question ratee et la reussir doit faire monter le score."""
    from mathsapp import content, status as st_mod, store
    from mathsapp.syllabus import load

    syl = load()
    cid = next((c.id for c in syl.all() if content.has_exercises(c.id)), None)
    if cid is None:
        return
    questions = content.quiz_sets(cid)[0]["qcm"]
    if len(questions) < 6:
        return

    # copie brute de toutes les colonnes : echeances et intervalles compris
    saved = [dict(r) for r in store.conn().execute(
        "SELECT * FROM question_result WHERE course_id=?", (cid,))]
    saved_attempts = list(store.attempts(cid))
    try:
        store.reset_question_history(cid)
        store.conn().execute("DELETE FROM quiz_attempt WHERE course_id=?", (cid,))
        store.conn().commit()

        # seance complete : une seule erreur
        wrong = questions[2]
        detail = {"answers": [{"id": q["id"], "ok": q["id"] != wrong["id"]}
                              for q in questions]}
        store.record_attempt(cid, len(questions), len(questions) - 1, detail, "1")
        first = st_mod.compute(syl)[cid]
        expected = int(round(100.0 * (len(questions) - 1) / len(questions)))
        check("score apres une seance complete", first.score_pct == expected,
              "%s %% (attendu %d %%)" % (first.score_pct, expected))

        # on refait uniquement la question ratee, et on la reussit
        store.record_attempt(cid, 1, 1, {"answers": [{"id": wrong["id"], "ok": True}]},
                             "1", partial=True)
        after = st_mod.compute(syl)[cid]
        check("le score monte apres correction de l'erreur",
              after.score_pct == 100 and after.answered == len(questions),
              "%s %% sur %d tentees" % (after.score_pct, after.answered))
        check("la seance partielle ne cree pas de tentative",
              len(store.attempts(cid)) == 1, "%d tentative(s)" % len(store.attempts(cid)))

        # et il redescend si on la rate de nouveau
        store.record_attempt(cid, 1, 0, {"answers": [{"id": wrong["id"], "ok": False}]},
                             "1", partial=True)
        again = st_mod.compute(syl)[cid]
        check("le score redescend si on la rate de nouveau",
              again.score_pct == expected, "%s %%" % again.score_pct)

        # couverture insuffisante : pas de maitrise sur deux bonnes reponses
        store.reset_question_history(cid)
        store.record_attempt(cid, 2, 2, {"answers": [{"id": questions[0]["id"], "ok": True},
                                                     {"id": questions[1]["id"], "ok": True}]},
                             "1", partial=True)
        thin = st_mod.compute(syl)[cid]
        check("100 % sur deux questions ne vaut pas maitrise",
              thin.score_pct == 100 and not thin.mastered and not thin.enough_answered,
              "%s %%, %d tentees, seuil %d" % (thin.score_pct, thin.answered,
                                               thin.questions_needed))
    finally:
        store.reset_question_history(cid)
        store.conn().execute("DELETE FROM quiz_attempt WHERE course_id=?", (cid,))
        for row in saved_attempts:
            store.conn().execute(
                "INSERT INTO quiz_attempt (course_id, finished_at, total, correct, detail) "
                "VALUES (?,?,?,?,?)",
                (cid, row["finished_at"], row["total"], row["correct"], row["detail"]))
        store.conn().commit()
        for row in saved:
            store.conn().execute(
                "INSERT OR REPLACE INTO question_result (%s) VALUES (%s)"
                % (", ".join(row), ", ".join("?" * len(row))), tuple(row.values()))
        store.conn().commit()
        restored = [dict(r) for r in store.conn().execute(
            "SELECT * FROM question_result WHERE course_id=?", (cid,))]
        key = lambda r: (r["set_id"], r["question_id"])
        check("historique reel restaure a l'identique",
              sorted(restored, key=key) == sorted(saved, key=key))


def test_sheet() -> None:
    """Fiche de revision : extraction, assemblage, export PDF."""
    import re
    from mathsapp import content
    from mathsapp.syllabus import load

    syl = load()
    with_sheet = [c.id for c in syl.all() if content.has_sheet(c.id)]
    with_course = [c.id for c in syl.all() if content.has_course(c.id)]
    if not with_course:
        check("fiche : aucun cours genere, test ignore", True)
        return

    cid = with_course[0]
    substance = content.substance(cid)
    check("substance extraite du cours", len(substance) > 2000,
          "%d caracteres" % len(substance))
    check("substance : enonces conserves",
          "[DEFINITION]" in substance or "[THEOREME]" in substance,
          substance[:60])

    if not with_sheet:
        check("fiche : aucune fiche generee, rendu non teste", True)
        return

    cid = with_sheet[0]
    page = content.render_sheet_page(cid, syl.title(cid), "light")
    text = page.read_text(encoding="utf-8")
    check("page de fiche assemblee",
          "katex.min.css" in text and "sheet.css" in text
          and "__BODY__" not in text and "__ASSETS__" not in text)
    printed = content.render_sheet_page(cid, syl.title(cid), "light", for_print=True)
    check("variante impression", 'class="print"' in printed.read_text(encoding="utf-8"))

    body = content.read_sheet(cid)
    blocks = re.findall(r"<h2>(.*?)</h2>", body)
    check("fiche structuree", len(blocks) >= 4, ", ".join(blocks[:4]))
    check("fiche : rappel actif present", 'class="qa"' in body)
    check("fiche : classes attendues seulement",
          not re.search(r'class="(?!sheet-head|meta|oneline|block|def|thm|method|'
                        r'trap|note|tag|formulas|check|qa|q|a|cols|mviz)', body),
          str(set(re.findall(r'class="([a-z-]+)"', body)) - {
              "sheet-head", "meta", "oneline", "block", "def", "thm", "method",
              "trap", "note", "tag", "formulas", "check", "qa", "q", "a", "cols",
              "mviz"}))

    # export PDF reel
    from mathsapp.paths import library_dir
    from mathsapp.ui.pdf_export import PdfExporter
    target = library_dir() / "_views" / "selftest.pdf"
    result = {}
    exporter = PdfExporter()
    exporter.finished.connect(lambda ok, msg: result.update(ok=ok, msg=msg))
    exporter.export(cid, syl.title(cid), target, settle_ms=400)
    ok = wait_until(lambda: "ok" in result, 45000)
    check("export PDF", ok and result.get("ok") and target.exists(),
          result.get("msg", "délai dépassé"))
    if target.exists():
        data = target.read_bytes()
        check("PDF valide", data[:5] == b"%PDF-" and len(data) > 20000,
              "%d ko" % (len(data) // 1024))
        target.unlink()


def test_bridge() -> None:
    """Le JavaScript des pages doit pouvoir rappeler l'application."""
    from mathsapp import content
    from mathsapp.paths import library_dir
    from mathsapp.ui.webview import WebView

    view = WebView(with_bridge=True)
    view.resize(900, 700)
    view.show()
    got: dict = {}
    view.bridge.ask_requested.connect(lambda t, h: got.update(ask=(t, h)))
    view.bridge.proof_help_requested.connect(lambda i, h, t: got.update(proof=(i, h)))
    view.bridge.quiz_finished.connect(lambda p: got.update(quiz=p))
    view.bridge.proof_status_changed.connect(lambda i, v: got.update(status=(i, v)))
    view.bridge.proof_draft_changed.connect(lambda i, t: got.update(draft=(i, t)))
    view.bridge.proof_review_requested.connect(lambda i, p: got.update(review=(i, p)))

    body = ('<h2>Section test</h2><p>Un peu de texte $a^2+b^2$.</p>'
            '<h2>Deuxieme section</h2><p>Suite, avec $$\\int_0^1 x\\,\\dd x$$.</p>'
            '<details class="proof" data-of="Theoreme test"><summary>Demonstration</summary>'
            '<div class="proof-body"><p>Preuve.</p></div></details>'
            '<div class="mviz" id="fig-t"></div>'
            '<script>mviz.plot("#fig-t", {xrange:[-2,2], yrange:[-1,4],'
            ' draw:function(g){g.curve(function(x){return x*x;});}});</script>')
    d = library_dir() / "_views"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "selftest.html"
    path.write_text(content.build_page(body, "Selftest", "light"), encoding="utf-8")

    loaded: dict = {}
    view.loadFinished.connect(lambda ok: loaded.update(ok=ok))
    view.load_file(path)
    check("page de test chargee", wait_until(lambda: "ok" in loaded) and loaded["ok"])
    wait(2500)

    probe: dict = {}
    view.page().runJavaScript(
        "document.querySelectorAll('.katex').length", lambda r: probe.update(katex=r))
    view.page().runJavaScript(
        "document.querySelectorAll('#fig-t canvas').length", lambda r: probe.update(canvas=r))
    view.page().runJavaScript(
        "document.querySelectorAll('#toc a').length", lambda r: probe.update(toc=r))
    view.page().runJavaScript(
        "!!document.getElementById('ask-bubble')", lambda r: probe.update(bubble=r))
    wait_until(lambda: len(probe) == 4, 8000)
    check("formules rendues par KaTeX", probe.get("katex", 0) >= 1, "%s formules" % probe.get("katex"))
    check("figure mviz dessinee", probe.get("canvas", 0) == 1)
    check("sommaire construit", probe.get("toc", 0) >= 1, "%s entrees" % probe.get("toc"))
    check("bouton de selection installe", bool(probe.get("bubble")))

    ready: dict = {}
    view.page().runJavaScript("typeof window.app", lambda r: ready.update(kind=r))
    wait_until(lambda: "kind" in ready, 5000)
    check("pont expose au JavaScript", ready.get("kind") == "object", str(ready))
    view.page().runJavaScript("app.askAbout('extrait choisi', 'Section test');")
    view.page().runJavaScript("app.openProofHelper('p1', 'Theoreme test', 'texte');")
    view.page().runJavaScript("app.quizFinished('{\"total\":2,\"correct\":1}');")
    view.page().runJavaScript("app.setProofStatus('p1', 'done');")
    view.page().runJavaScript("app.saveProofDraft('p1', 'Soit x dans E. $x^2 \\geq 0$.');")
    view.page().runJavaScript("app.reviewProof('p1', '{\"attempt\":\"ma preuve\"}');")
    ok = wait_until(lambda: len(got) == 6, 8000)
    check("pont JS -> application", ok, str(sorted(got)))
    check("  selection de texte transmise", got.get("ask") == ("extrait choisi", "Section test"))
    check("  aide a la demonstration transmise", got.get("proof") == ("p1", "Theoreme test"))
    check("  fin de QCM transmise", '"correct":1' in (got.get("quiz") or ""))
    check("  statut de demonstration transmis", got.get("status") == ("p1", "done"))
    check("  brouillon de demonstration transmis",
          got.get("draft", ("", ""))[0] == "p1" and "x^2" in got.get("draft", ("", ""))[1])
    check("  demande de correction transmise",
          got.get("review", ("", ""))[0] == "p1" and "ma preuve" in got.get("review", ("", ""))[1])
    view.deleteLater()


def test_reading_position() -> None:
    """Reprendre la lecture : section et decalage relatif, pas des pixels."""
    import json
    from mathsapp import content, store
    from mathsapp.paths import library_dir
    from mathsapp.ui.dashboard import ago
    from mathsapp.ui.webview import WebView

    fake = "_selftest_lecture"
    try:
        store.save_reading_position(fake, "s-1", "Deuxième section", 1, 0.4, 0.5)
        pos = store.reading_position(fake)
        check("position de lecture enregistree",
              pos and pos["section_title"] == "Deuxième section"
              and abs(pos["section_offset"] - 0.4) < 1e-9, str(pos))
        store.save_reading_position(fake, "s-1", "Deuxième section", 1, 0.9, 0.97)
        check("une seule position par cours",
              store.conn().execute("SELECT COUNT(*) n FROM reading_position WHERE course_id=?",
                                   (fake,)).fetchone()["n"] == 1)
        check("fin de cours : pas de reprise", not store.resumable(store.reading_position(fake)))
        check("tout debut : pas de reprise",
              not store.resumable({"section_title": "Intro", "section_index": 0,
                                   "fraction": 0.0}))
        check("milieu du cours : reprise proposee", store.resumable(pos))
    finally:
        store.clear_reading_position(fake)
    check("anciennete lisible", ago(1000.0, now=1000.0 + 7200) == "il y a 2 h"
          and ago(0.0, now=86400 * 1.5) == "hier")

    view = WebView(with_bridge=True)
    view.resize(900, 500)
    view.show()
    got: list = []
    view.bridge.reading_position_changed.connect(got.append)
    filler = "".join("<p>Paragraphe %d, avec $x_%d$.</p>" % (i, i) for i in range(40))
    body = ("<h2>Première section</h2>%s<h2>Deuxième section</h2>%s"
            "<h2>Troisième section</h2>%s" % (filler, filler, filler))
    d = library_dir() / "_views"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "selftest_reading.html"
    path.write_text(content.build_page(body, "Lecture", "light"), encoding="utf-8")
    loaded: dict = {}
    view.loadFinished.connect(lambda ok: loaded.update(ok=ok))
    view.load_file(path)
    wait_until(lambda: "ok" in loaded)
    wait(1200)

    def js(code: str):
        box: dict = {}
        view.page().runJavaScript(code, lambda r: box.update(r=r))
        wait_until(lambda: "r" in box, 5000)
        return box.get("r")

    saved = {"section_id": "ancienne-ancre", "section_title": "Deuxième section",
             "section_index": 1, "section_offset": 0.5, "fraction": 0.5}
    shown = js("window.initReading(%s, %s, false)" % (json.dumps(fake), json.dumps(saved)))
    check("bandeau « Reprendre à » propose (section retrouvee par son titre)",
          shown is True and js("!!document.getElementById('resume-banner')") is True)
    check("pas de defilement sans clic", js("window.scrollY") == 0)
    js("document.querySelector('#resume-banner .resume-go').click(); true")
    wait(1200)
    # objet serialise en JSON : runJavaScript ne convertit pas fiablement un objet JS
    here = json.loads(js("JSON.stringify(window.readingPosition())") or "null") or {}
    check("reprise sur la bonne section", here.get("title") == "Deuxième section"
          and 0.3 < here.get("offset", 0) < 0.7, str(here))
    check("bandeau retire apres usage", js("!!document.getElementById('resume-banner')") is False)
    check("sauvegarde apres defilement (anti-rebond)",
          wait_until(lambda: bool(got), 4000)
          and json.loads(got[-1]).get("course") == fake, str(got[-1:]))
    gone = dict(saved, section_title="Section disparue")
    check("section disparue : rien a reprendre, sans erreur",
          js("window.initReading(%s, %s, false)" % (json.dumps(fake), json.dumps(gone))) is False
          and js("!!document.getElementById('resume-banner')") is False)
    view.deleteLater()


def test_quiz_progress() -> None:
    """QCM : la tentative est ecrite a chaque reponse et se reprend a l'identique."""
    import json
    from mathsapp import content, store
    from mathsapp.paths import ASSETS_DIR, library_dir
    from mathsapp.ui.session_page import SessionPage
    from mathsapp.ui.webview import WebView

    key = store.course_progress_key("_selftest_qcm", "1")
    try:
        store.save_quiz_progress(key, {"setId": "1", "answered": 1}, "_selftest_qcm", "1")
        store.save_quiz_progress(key, {"setId": "1", "answered": 2}, "_selftest_qcm", "1")
        check("tentative en cours : un seul etat par serie",
              store.course_quiz_progress("_selftest_qcm") == {"1": {"setId": "1", "answered": 2}})
    finally:
        store.clear_quiz_progress(key)
    check("tentative effacee", store.quiz_progress(key) is None)
    check("cle de seance : un rappel par cours",
          SessionPage.progress_key("refresher", "2026-01-01", "c1")
          != SessionPage.progress_key("refresher", "2026-01-01", "c2"))

    def question(i: int, text: str = "") -> dict:
        return {"id": "q%d" % i, "question": "<p>%s Question %d ?</p>" % (text, i),
                "choices": ["a", "b", "c", "d"], "answer": 1, "difficulty": 1,
                "explanation": "<p>Parce que.</p>"}

    def page(qcm: list, progress: dict) -> pathlib.Path:
        sets = [{"id": "1", "title": "Série 1", "qcm": qcm}]
        tpl = (ASSETS_DIR / "quiz.html").read_text(encoding="utf-8")
        html = (tpl.replace("__THEME__", "light").replace("__ASSETS__", content.assets_url())
                   .replace("__SETS__", json.dumps(sets)).replace("__HISTORY__", "{}"))
        html = content.with_quiz_progress(html, progress, "_selftest_qcm")
        d = library_dir() / "_views"
        d.mkdir(parents=True, exist_ok=True)
        path = d / "selftest_quiz.html"
        path.write_text(html, encoding="utf-8")
        return path

    view = WebView(with_bridge=True)
    view.resize(900, 700)
    view.show()
    saved: list = []
    finished: list = []
    view.bridge.quiz_progress_saved.connect(saved.append)
    view.bridge.quiz_finished.connect(finished.append)

    def load(path) -> None:
        box: dict = {}
        view.loadFinished.connect(lambda ok: box.update(ok=ok))
        view.load_file(path)
        wait_until(lambda: "ok" in box)
        wait(900)

    def js(code: str):
        box: dict = {}
        view.page().runJavaScript(code, lambda r: box.update(r=r))
        wait_until(lambda: "r" in box, 5000)
        return box.get("r")

    qcm = [question(1), question(2), question(3)]
    load(page(qcm, {}))
    js("document.getElementById('go').click(); true")
    js("document.querySelector('.choice[data-i=\"1\"]').click();"
       "document.getElementById('go').click(); true")
    ok = wait_until(lambda: bool(saved), 4000)
    state = json.loads(saved[-1]) if saved else {}
    check("reponse validee : etat ecrit aussitot", ok and state.get("answered") == 1
          and state.get("order") == ["q1", "q2", "q3"]
          and state.get("answers", [{}])[0].get("chosen") == 1
          and state.get("courseId") == "_selftest_qcm", str(state)[:200])

    load(page(qcm, {"1": state}))
    label = js("(document.getElementById('resume')||{}).textContent")
    check("reouverture : « Reprendre (question 2/3) » propose",
          label == "Reprendre (question 2/3)", str(label))
    js("document.getElementById('resume').click(); true")
    check("reprise sur la premiere question sans reponse",
          "Question 2 / 3" in (js("document.querySelector('.qhead').textContent") or ""))
    js("document.getElementById('prev').click(); true")
    check("reprise : reponse et correction precedentes visibles",
          js("!!document.querySelector('.choice.good') && !!document.querySelector('.verdict')")
          is True)
    js("document.getElementById('go').click(); true")
    for _ in range(2):
        js("document.querySelector('.choice[data-i=\"0\"]').click();"
           "document.getElementById('go').click(); document.getElementById('go').click(); true")
    wait_until(lambda: bool(finished), 4000)
    js("var j=document.querySelector('[data-jump]'); if (j) j.click(); true")
    js("var g=document.getElementById('go'); if (g) g.click(); true")
    js("var g=document.getElementById('go'); if (g) g.click(); true")
    wait(600)
    data = json.loads(finished[0]) if finished else {}
    check("tentative reprise terminee normalement, comptee une seule fois",
          len(finished) == 1 and data.get("total") == 3 and data.get("correct") == 1,
          "%d fin(s), %s" % (len(finished), str(data)[:120]))

    changed = [question(1, "Nouvelle"), question(2), question(3)]
    load(page(changed, {"1": state}))
    check("serie regeneree : pas de reprise, recommencer propose sans erreur",
          js("!document.getElementById('resume') && !!document.getElementById('restart')") is True)
    view.deleteLater()


def test_proof_editor() -> None:
    """La page des demonstrations doit offrir un editeur utilisable."""
    import json
    from mathsapp import content
    from mathsapp.paths import ASSETS_DIR, library_dir
    from mathsapp.ui.webview import WebView

    data = {"proofs": [{
        "id": "d1", "difficulty": 2, "title": "Test $\\lor$",
        "statement": "<p>Montrer que $p \\lor \\neg p$ est une tautologie.</p>",
        "hints": ["<p>Table de verite.</p>"],
        "steps": [{"title": "Cas", "content": "<p>Deux cas.</p>"}],
        "solution": "<p>Immediat.</p>"}]}
    tpl = (ASSETS_DIR / "proofs.html").read_text(encoding="utf-8")
    page = (tpl.replace("__THEME__", "light")
               .replace("__ASSETS__", content.assets_url())
               .replace("__DATA__", json.dumps(data, ensure_ascii=False))
               .replace("__STATUS__", "{}")
               .replace("__DRAFTS__", json.dumps({"d1": "Soit $p$ une proposition."})))
    d = library_dir() / "_views"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "selftest_proofs.html"
    path.write_text(page, encoding="utf-8")

    view = WebView(with_bridge=True)
    view.resize(1200, 900)
    view.show()
    got: dict = {}
    view.bridge.proof_draft_changed.connect(lambda i, t: got.update(draft=(i, t)))
    view.bridge.proof_review_requested.connect(lambda i, p: got.update(review=(i, p)))
    loaded: dict = {}
    view.loadFinished.connect(lambda ok: loaded.update(ok=ok))
    view.load_file(path)
    wait_until(lambda: "ok" in loaded)
    wait(2500)

    probe: dict = {}
    view.page().runJavaScript("!!document.getElementById('draft')", lambda r: probe.update(ta=r))
    view.page().runJavaScript("document.getElementById('draft').value",
                              lambda r: probe.update(val=r))
    view.page().runJavaScript("document.querySelectorAll('.pal-tab').length",
                              lambda r: probe.update(tabs=r))
    view.page().runJavaScript("document.querySelectorAll('.pal-key').length",
                              lambda r: probe.update(keys=r))
    wait_until(lambda: len(probe) == 4, 8000)
    check("editeur de demonstration present", bool(probe.get("ta")))
    check("brouillon precedent recharge", "proposition" in (probe.get("val") or ""))
    check("palette de symboles", probe.get("tabs", 0) == 6 and probe.get("keys", 0) >= 10,
          "%s categories, %s touches" % (probe.get("tabs"), probe.get("keys")))

    # insertion depuis la palette, puis demande de correction
    view.page().runJavaScript(
        "var t=document.getElementById('draft'); t.focus();"
        "t.setSelectionRange(t.value.length, t.value.length);"
        "document.querySelectorAll('.pal-key')[0].click();")
    wait(1200)
    view.page().runJavaScript("document.getElementById('draft').value",
                              lambda r: probe.update(after=r))
    wait_until(lambda: "after" in probe, 5000)
    check("insertion depuis la palette", "\\forall" in (probe.get("after") or ""),
          repr((probe.get("after") or "")[-30:]))
    ok = wait_until(lambda: "draft" in got, 8000)
    check("brouillon enregistre automatiquement", ok)

    view.page().runJavaScript("document.getElementById('review').click();")
    ok = wait_until(lambda: "review" in got, 8000)
    check("correction demandable", ok and "attempt" in (got.get("review", ("", ""))[1]))
    view.deleteLater()


def test_queue() -> None:
    """Ordre d'affichage et relance, sans lancer de vraie generation."""
    from mathsapp.generation.queue import (
        CANCELLED, DONE, ERROR, QUEUED, RUNNING, GenerationQueue,
    )
    from mathsapp.ui.queue_panel import QueuePanel

    queue = GenerationQueue()
    queue._pool.start = lambda task: None      # on n'execute rien
    for cid, title in [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma"), ("d", "Delta")]:
        queue.enqueue(cid, title)
    queue.jobs[0].state = DONE
    queue.jobs[1].state = ERROR
    queue.jobs[2].state = RUNNING
    queue.jobs[3].state = QUEUED

    panel = QueuePanel(queue)
    panel.resize(700, 300)
    panel.refresh()
    order = [panel.tree.topLevelItem(i).text(0) for i in range(panel.tree.topLevelItemCount())]
    check("file : ce qui tourne en tete", order[0] == "Gamma", str(order))
    check("file : l'attente avant les termines",
          order.index("Delta") < order.index("Beta") < order.index("Alpha"), str(order))
    check("bouton de relance visible", panel.btn_retry.isVisible() or panel.btn_retry.isVisibleTo(panel))

    import time as _time
    from mathsapp.generation.queue import SILENT_AFTER, SLOW_AFTER
    live = queue.jobs[2]                      # celui marque RUNNING
    live.started_at = _time.time() - 120
    live.last_activity = _time.time()
    check("travail actif considere vivant", live.health == "vivant", live.health)
    live.last_activity = _time.time() - (SLOW_AFTER + 5)
    check("silence moyen signale comme lent", live.health == "lent", live.health)
    live.last_activity = _time.time() - (SILENT_AFTER + 5)
    check("silence long signale comme muet", live.health == "muet", live.health)
    state, silence, worst = queue.health()
    check("sante globale remontee",
          state == "muet" and worst is live and silence > SILENT_AFTER,
          "%s depuis %.0f s" % (state, silence))
    live.last_activity = _time.time()
    check("retour a la normale", queue.health()[0] == "vivant")
    check("duree ecoulee mesuree", 115 < live.elapsed < 130, "%.0f s" % live.elapsed)

    from mathsapp.generation import claude_cli
    from mathsapp.generation.queue import explain, pause_reason
    check("raison d'un echec transitoire",
          [claude_cli.transient_reason(m) for m in ("API Error: 429 rate limit", "ECONNRESET")]
          == ["limite de débit de l'API", "erreur réseau"])
    live.note_progress("Section 2/5 — limite de débit de l'API, nouvelle tentative dans 30 s "
                       "(essai 2/3) · API Error: 429 rate limit")
    status, reason = queue.explain(live)
    check("pause sur limite de debit expliquee",
          status == "en pause" and reason.startswith("limite de débit de l'API, nouvelle tentative"),
          "%s : %s" % (status, reason))
    check("dernier message d'erreur conserve", "429" in live.last_notice, live.last_notice)
    live.retry_until = 0.0
    check("fin de pause", queue.explain(live)[0] == "en cours", str(queue.explain(live)))
    status, reason = explain(queue.jobs[3], 2, 2)
    check("attente sur la limite de concurrence",
          status == "en attente" and "gen/concurrency" in reason, reason)
    queue.jobs[1].error = "Délai dépassé.\ndétail"
    check("cours interrompu par un echec", queue.pause_reason("b") == "échec : Délai dépassé.",
          queue.pause_reason("b"))
    check("cours interrompu avant cette session",
          pause_reason([], "b") == "interrompu lors d'une session précédente")
    queue.jobs[0].state = CANCELLED
    check("cours arrete manuellement", pause_reason(queue.jobs, "a") == "arrêté manuellement")
    queue.jobs[0].state = DONE

    before = len(queue.jobs)
    queue.retry("b")
    job = queue.job_for("b")
    check("relance d'un echec", job is not None and job.state == QUEUED,
          "%d -> %d travaux" % (before, len(queue.jobs)))
    panel.deleteLater()


def test_resume() -> None:
    """Un cours interrompu doit etre reconnu comme tel, pas comme termine."""
    import json
    from mathsapp import content, status as st_mod
    from mathsapp.generation.pipeline import plan_fingerprint
    from mathsapp.paths import course_dir, library_dir
    from mathsapp.syllabus import load

    cid = "alg-corps"          # cours de test, jamais genere
    content.delete_course(cid)
    plan = {"hook": "t", "sections": [{"id": "s%d" % i, "title": "S%d" % i,
                                       "goal": "g", "content": "c"} for i in range(4)],
            "proved_in_course": [], "left_as_exercise": []}
    content.write_json(cid, content.PLAN, plan)
    state = content.generation_state(cid)
    check("plan seul = interrompu", state["partial"] and state["sections_done"] == 0,
          str(state))

    fingerprint = plan_fingerprint(plan)
    for i in range(2):
        content.write_section(cid, i, fingerprint, "<h2>S%d</h2>" % i + "x" * 300)
    content.write_body(cid, "<h2>S0</h2>" + "x" * 300)
    state = content.generation_state(cid)
    check("sections en cache comptees", state["sections_done"] == 2, str(state))
    check("corps present mais cours incomplet",
          content.has_course(cid) and not content.is_complete(cid))

    syl = load()
    statuses = st_mod.compute(syl)
    check("statut « incomplet »", statuses[cid].state == st_mod.PARTIAL,
          statuses[cid].state)
    check("liste des interrompus", cid in st_mod.incomplete(syl, statuses))

    # un plan different invalide le cache
    plan2 = dict(plan)
    plan2["sections"] = plan["sections"] + [{"id": "s4", "title": "S4", "goal": "g",
                                             "content": "c"}]
    content.write_json(cid, content.PLAN, plan2)
    check("cache invalide si le plan change",
          content.generation_state(cid)["sections_done"] == 0)
    content.delete_course(cid)
    d = course_dir(cid)
    if d.is_dir():
        for sub in sorted(d.rglob("*"), reverse=True):
            sub.rmdir() if sub.is_dir() else sub.unlink()
        d.rmdir()


def test_watchdog() -> None:
    """Un flux muet doit etre interrompu, et l'annulation doit rester possible."""
    import stat
    import threading
    import time as _time
    from mathsapp.generation import claude_cli as cc
    from mathsapp.paths import library_dir

    fake = library_dir() / "_views" / "fake_hang.sh"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = \"--version\" ]; then echo '0.0.0 (fake)'; exit 0; fi\n"
        "echo '{\"type\":\"stream_event\",\"event\":{\"type\":\"content_block_delta\","
        "\"delta\":{\"type\":\"text_delta\",\"text\":\"debut\"}}}'\n"
        "sleep 600\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    # On vise le faux binaire par parametre : toucher aux preferences
    # interromprait une generation en cours dans l'application ouverte.
    opts = {"exe": str(fake), "stall_timeout": 4}
    try:
        start = _time.time()
        message = ""
        try:
            cc.run("test", "sonnet", retries=1, **opts)
        except cc.ClaudeError as exc:
            message = str(exc)
        elapsed = _time.time() - start
        check("flux muet interrompu", "silence" in message.lower(), message[:60])
        check("interruption rapide", elapsed < 20, "%.0f s" % elapsed)
        check("panne muette jugee transitoire", cc.is_transient(message))

        stop = [False]
        threading.Timer(2.0, lambda: stop.__setitem__(0, True)).start()
        start = _time.time()
        cancelled = False
        try:
            cc.run("test", "sonnet", cancel=lambda: stop[0], retries=3, **opts)
        except cc.Cancelled:
            cancelled = True
        except cc.ClaudeError:
            pass
        check("annulation possible pendant un blocage",
              cancelled and _time.time() - start < 12,
              "%.0f s" % (_time.time() - start))
    finally:
        if fake.exists():
            fake.unlink()


def test_views() -> None:
    from mathsapp.ui.main_window import MainWindow, PAGE_GRAPH, PAGE_HOME, PAGE_LIBRARY
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    wait(600)
    window.go(PAGE_LIBRARY)
    check("bibliotheque construite",
          window.library.tree.topLevelItemCount() == len(window.syl.domains),
          "%d domaines affiches" % window.library.tree.topLevelItemCount())
    window.go(PAGE_GRAPH)
    check("graphe construit",
          len(window.graph.scene.nodes) == len(window.syl.courses),
          "%d noeuds" % len(window.graph.scene.nodes))
    window.go(PAGE_HOME)
    first = window.syl.topo[0]
    window.open_course(first)
    check("page de cours ouverte", window.course_page.course.id == first)
    window.toggle_theme()
    window.toggle_theme()
    check("bascule de theme", True)

    # la fenetre doit tenir sur un ecran de 1920 px avec le chat ouvert, meme sur
    # le cours aux prerequis les plus nombreux
    widest = max(window.syl.all(), key=lambda c: sum(len(window.syl.title(p)) for p in c.prereqs))
    window.open_course(widest.id)
    window.focus_chat()
    QApplication.instance().processEvents()
    width = window.minimumSizeHint().width()
    parts = {"barre": window.topbar, "pages": window.stack, "chat": window.chat_dock,
             "cours": window.course_page, "biblio": window.library, "td": window.td_page,
             "questions": window.questions_page, "seance": window.session,
             "graphe": window.graph, "accueil": window.dashboard, "file": window.queue_dock}
    check("la fenetre tient sur l'ecran avec le chat ouvert", width <= 1600,
          "%d px (%s) ; %s" % (width, widest.id, ", ".join(
              "%s %d" % (k, w.minimumSizeHint().width()) for k, w in parts.items())))
    window.chat_dock.setVisible(False)
    window.open_course(first)

    # file de generation masquee : pastille, alerte discrete, choix persistant
    from mathsapp import settings as settings_mod
    before_hidden = settings_mod.get("ui/queue_hidden")
    try:
        window.set_queue_hidden(False)
        QApplication.instance().processEvents()
        check("file affichee : bouton Masquer present",
              window.queue_dock.isVisible() and window.queue_panel.btn_hide.text() == "Masquer")
        window.queue_panel.btn_hide.click()
        QApplication.instance().processEvents()
        check("file masquee : panneau ferme, pastille visible",
              not window.queue_dock.isVisible() and not window.queue_badge.isHidden()
              and window.btn_queue.isHidden())
        check("file masquee : choix enregistre", settings_mod.get("ui/queue_hidden") == 1)
        window._reveal_queue()
        check("file masquee : pas de reouverture automatique", not window.queue_dock.isVisible())
        window.notice.hide()
        window._on_job_done(first, "sheet", False, "échec simulé")
        QApplication.instance().processEvents()
        check("echec pendant que la file est masquee : pastille en alerte, rien ne s'ouvre",
              window.queue_badge_state() == "alert" and not window.queue_dock.isVisible()
              and window.notice.isHidden())
        window.toggle_queue()
        QApplication.instance().processEvents()
        check("raccourci : la file se rouvre et l'alerte est levee",
              window.queue_dock.isVisible() and window.queue_badge_state() == "hidden-off"
              and settings_mod.get("ui/queue_hidden") == 0)
        window.toggle_queue()
        check("raccourci : la file se masque de nouveau",
              not window.queue_dock.isVisible()
              and window.queue_badge_state() in ("empty", "running", "done"))
    finally:
        window.set_queue_hidden(bool(before_hidden))
        settings_mod.put("ui/queue_hidden", before_hidden)
        window.queue_dock.setVisible(False)
        window.notice.hide()

    from mathsapp.ui.course_page import TAB_EXERCISES
    check("cours ordinaire : pas d'onglet Exercices du cours",
          not window.course_page.tabs.isTabVisible(TAB_EXERCISES))

    window.open_assistant()
    check("assistant ouvert", window.chat.is_assistant and window.chat_dock.isVisible())
    check("assistant : etat fourni a Claude",
          "RÉGLAGES MODIFIABLES" in window.chat.session.system)
    window.chat.show_actions([{"id": "t1", "type": "open", "page": "graph",
                               "label": "Ouvrir le graphe", "detail": ""}])
    window.chat.view.bridge.runAction("t1")
    check("assistant : une action validee s'execute",
          window.stack.currentIndex() == PAGE_GRAPH)
    window.go(PAGE_HOME)
    window.chat.view.bridge.runAction("t1")
    check("assistant : une carte faite ne s'execute pas deux fois",
          window.stack.currentIndex() == PAGE_HOME)
    window.chat.set_context(None, "general")

    from mathsapp.ui.main_window import PAGE_QUESTIONS
    from mathsapp import questions as questions_mod, store as store_mod
    window.go(PAGE_QUESTIONS)
    qpanel = window.questions_page.panel
    check("page des questions ouverte",
          window.stack.currentIndex() == PAGE_QUESTIONS and qpanel.session is not None
          and qpanel.session.mode == "question")
    check("questions : catalogue fourni a Claude", "CATALOGUE DU CURSUS" in qpanel.session.system)
    opened = []
    window.questions_page.course_opened.disconnect(window.open_course_at)
    window.questions_page.course_opened.connect(lambda c, s: opened.append((c, s)))
    qpanel.view.bridge.openCourseAt(first, "Une section")
    check("questions : lien vers une section transmis", opened == [(first, "Une section")])
    store_mod.delete_empty_threads(questions_mod.PREFIX)

    from mathsapp.ui.main_window import PAGE_TD
    window.go(PAGE_TD)
    check("page des TD ouverte", window.stack.currentIndex() == PAGE_TD,
          "%d TD" % window.td_page.picker.count())
    emitted = []
    window.td_page.course_opened.disconnect(window.open_course)
    window.td_page.course_opened.connect(emitted.append)
    window.td_page.view.bridge.openCourse(first)
    check("lien vers un cours depuis une correction", emitted == [first])
    window.td_page.course_opened.disconnect(emitted.append)
    window.td_page.course_opened.connect(window.open_course)
    window.close()


def test_chat() -> None:
    from mathsapp.ui.chat_panel import ChatPanel
    from mathsapp.syllabus import load
    panel = ChatPanel(load())
    panel.resize(500, 700)
    panel.show()
    wait(1500)
    panel.set_context(None, "selftest-chat")
    panel.composer.setPlainText("Reponds exactement : PONG")
    panel.send()
    ok = wait_until(lambda: not panel.busy, 120000)
    check("aller-retour avec Claude", ok and bool(panel.session.history()),
          panel.session.history()[-1]["content"][:60] if panel.session.history() else "")
    panel.session.reset()
    panel.deleteLater()


FAKE_CODEX = '#!/usr/bin/env python3\nimport json, os, sys\nargs = sys.argv[1:]\nif args[:1] == ["--version"]:\n    print("codex-cli 0.0-faux"); sys.exit(0)\nif os.environ.get("FAKE_CODEX_REJECT") in args:\n    print("error: unexpected argument \'%s\' found" % os.environ["FAKE_CODEX_REJECT"], file=sys.stderr)\n    sys.exit(2)\nprompt = args[-1]\ndef opt(name):\n    return args[args.index(name) + 1] if name in args else None\nif "--output-schema" in args or "JSON valide" in prompt:\n    answer = json.dumps({"qcm": [{"id": "q1"}], "vu": "CONSIGNES PERMANENTES" in prompt})\nelse:\n    answer = "<p>ok %d</p>" % prompt.count("### Question")\nprint(json.dumps({"type": "item.completed", "item": {"type": "reasoning", "text": "hmm"}}))\nfor i in range(0, len(answer), 5):\n    print(json.dumps({"type": "agent_message_delta", "delta": answer[i:i + 5]}), flush=True)\nprint(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": answer}}))\nif opt("--output-last-message"):\n    open(opt("--output-last-message"), "w").write(answer)\n'


def main() -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication([])
    from mathsapp.ui import theme
    app.setStyleSheet(theme.stylesheet())

    print("\n--- syllabus ---")
    test_syllabus()
    print("\n--- integrite des prompts ---")
    test_prompts_integrity()
    print("\n--- moteur codex ---")
    test_codex_backend()
    print("\n--- cours importes ---")
    test_course_import()
    print("\n--- questions libres ---")
    test_questions()
    print("\n--- assistant ---")
    test_assistant()
    print("\n--- inegalites dans les formules ---")
    test_math_lt()
    print("\n--- quiz du jour et rappels cibles ---")
    test_refresher()
    print("\n--- sujets de TD ---")
    test_td()
    print("\n--- extension du syllabus ---")
    test_syllabus_extra()
    print("\n--- progression ---")
    test_store()
    print("\n--- TD d'entrainement ---")
    test_training()
    print("\n--- brouillons des demonstrations ---")
    test_brouillon()
    print("\n--- assemblage des pages ---")
    test_pages()
    print("\n--- contexte entre sections ---")
    test_section_context()
    print("\n--- habitude et progression ---")
    test_gamify()
    print("\n--- registres de relecture ---")
    test_review_modes()
    print("\n--- score du cours ---")
    test_score_updates()
    print("\n--- series de QCM ---")
    test_quiz_sets()
    print("\n--- equilibre des QCM ---")
    test_qcm_balance()
    print("\n--- fiche de revision ---")
    test_sheet()
    print("\n--- pont javascript ---")
    test_bridge()
    print("\n--- reprendre la lecture ---")
    test_reading_position()
    print("\n--- sauvegarde des QCM a chaque reponse ---")
    test_quiz_progress()
    print("\n--- editeur de demonstration ---")
    test_proof_editor()
    print("\n--- reprise apres interruption ---")
    test_resume()
    print("\n--- file de generation ---")
    test_queue()
    print("\n--- chien de garde ---")
    test_watchdog()
    print("\n--- vues ---")
    test_views()
    if "--chat" in sys.argv:
        print("\n--- chat (appel reel au modele) ---")
        test_chat()

    for widget in app.topLevelWidgets():
        widget.close()
    wait(200)

    failed = [name for ok, name, _ in RESULTS if not ok]
    print("\n%d verifications, %d echec(s)" % (len(RESULTS), len(failed)))
    for name in failed:
        print("  -", name)
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    # QtWebEngine se plaint bruyamment a la destruction du profil ; on sort
    # sans laisser Python demonter l'arbre d'objets.
    os._exit(code)
