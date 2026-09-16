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
        path = syl.track_path(tid)
        seen: set = set()
        ok = True
        for cid in path:
            if any(p not in seen for p in syl.get(cid).prereqs):
                ok = False
                break
            seen.add(cid)
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
                   "QCM_REPAIR_SCHEMA", "DAILY_SCHEMA", "TD_SCHEMA"):
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

    text = ('<p>Voici.</p><actions>[{"type": "generate_courses", "courses": '
            '["pro-convergences", "pro-esperance", "inexistant", "pro-espaces"]},'
            '{"type": "set_setting", "key": "gen/section_parallel", "value": "4"},'
            '{"type": "set_setting", "key": "claude/binary", "value": "rm"},'
            '{"type": "set_setting", "key": "goal/bricks", "value": 99},'
            '{"type": "open", "page": "course", "course": "Chaînes de Markov"},'
            '{"type": "modify_app", "request": "court"},'
            '{"type": "inconnu"}]</actions>')
    visible, actions = assistant.parse_actions(text, syl)
    kinds = [a["type"] for a in actions]
    check("assistant : texte sans le bloc d'actions", visible == "<p>Voici.</p>", visible)
    check("assistant : actions invalides ecartees",
          kinds == ["generate_courses", "set_setting", "open"], str(kinds))
    gen = actions[0]
    check("assistant : cours inconnus et deja rediges ecartes",
          "inexistant" not in gen["courses"] and "pro-espaces" not in gen["courses"],
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


def main() -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication([])
    from mathsapp.ui import theme
    app.setStyleSheet(theme.stylesheet())

    print("\n--- syllabus ---")
    test_syllabus()
    print("\n--- integrite des prompts ---")
    test_prompts_integrity()
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
