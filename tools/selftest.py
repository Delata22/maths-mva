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
    print("\n--- extension du syllabus ---")
    test_syllabus_extra()
    print("\n--- progression ---")
    test_store()
    print("\n--- assemblage des pages ---")
    test_pages()
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
