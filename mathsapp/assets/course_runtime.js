/* Runtime de la page de cours : rendu LaTeX, sommaire, pont vers l'app. */
(function () {
  'use strict';

  var bridge = null;

  function connectBridge(done) {
    if (typeof QWebChannel === 'undefined' || !window.qt || !window.qt.webChannelTransport) {
      return done();
    }
    new QWebChannel(window.qt.webChannelTransport, function (channel) {
      bridge = channel.objects.app || null;
      window.app = bridge;   // expose pour le debogage et les tests
      done();
    });
  }

  // ------------------------------------------------------------------ KaTeX
  function renderMath() { renderMathIn(document.body); }

  function renderMathIn(el) {
    if (typeof renderMathInElement === 'undefined') return;
    renderMathInElement(el, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '\\[', right: '\\]', display: true },
        { left: '$', right: '$', display: false },
        { left: '\\(', right: '\\)', display: false }
      ],
      ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option'],
      throwOnError: false,
      strict: false,
      output: 'html',
      macros: {
        '\\R': '\\mathbb{R}', '\\N': '\\mathbb{N}', '\\Z': '\\mathbb{Z}',
        '\\Q': '\\mathbb{Q}', '\\C': '\\mathbb{C}', '\\E': '\\mathbb{E}',
        '\\P': '\\mathbb{P}', '\\1': '\\mathbf{1}',
        '\\norm': '\\left\\lVert #1 \\right\\rVert', '\\abs': '\\left| #1 \\right|',
        '\\scal': '\\left\\langle #1 , #2 \\right\\rangle',
        '\\argmin': '\\operatorname{arg\\,min}', '\\argmax': '\\operatorname{arg\\,max}',
        '\\Var': '\\operatorname{Var}', '\\Cov': '\\operatorname{Cov}',
        '\\rank': '\\operatorname{rang}', '\\tr': '\\operatorname{tr}',
        '\\diag': '\\operatorname{diag}', '\\Id': '\\mathrm{Id}',
        '\\dd': '\\mathrm{d}', '\\eps': '\\varepsilon'
      }
    });
  }

  // --------------------------------------------------------------- sommaire
  function slug(s, i) {
    return (s.toLowerCase()
      .normalize('NFD').replace(/[̀-ͯ]/g, '')
      .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'section') + '-' + i;
  }

  function buildToc() {
    var toc = document.getElementById('toc');
    if (!toc) return;
    var heads = document.querySelectorAll('article h2, article h3');
    if (heads.length < 2) { toc.style.display = 'none'; return; }
    var box = document.createElement('nav');
    var title = document.createElement('div');
    title.className = 'toc-title';
    title.textContent = 'Plan du cours';
    box.appendChild(title);
    var links = [];
    Array.prototype.forEach.call(heads, function (h, i) {
      if (!h.id) h.id = slug(h.textContent, i);
      var a = document.createElement('a');
      a.href = '#' + h.id;
      // on copie le HTML brut : KaTeX rendra le sommaire en meme temps que
      // le corps du cours, au lieu d'y recopier du texte deja rendu
      a.innerHTML = h.innerHTML;
      a.className = h.tagName === 'H3' ? 'lvl3' : 'lvl2';
      box.appendChild(a);
      links.push({ a: a, h: h });
    });
    toc.appendChild(box);

    var ticking = false;
    function spy() {
      ticking = false;
      var best = null;
      links.forEach(function (l) {
        if (l.h.getBoundingClientRect().top < 120) best = l;
      });
      links.forEach(function (l) { l.a.classList.toggle('active', l === best); });
      if (best && toc.scrollHeight > toc.clientHeight) {
        var top = best.a.offsetTop - toc.clientHeight / 2;
        if (Math.abs(toc.scrollTop - top) > 90) toc.scrollTop = top;
      }
    }
    window.addEventListener('scroll', function () {
      if (!ticking) { ticking = true; requestAnimationFrame(spy); }
    }, { passive: true });
    spy();
  }

  // ------------------------------------------------------------- preuves
  function decorateProofs() {
    var proofs = document.querySelectorAll('details.proof');
    Array.prototype.forEach.call(proofs, function (d, i) {
      if (!d.id) d.id = 'proof-' + (i + 1);
      var sum = d.querySelector('summary');
      if (!sum) {
        sum = document.createElement('summary');
        sum.textContent = 'Démonstration';
        d.insertBefore(sum, d.firstChild);
      }
      if (d.querySelector('.proof-help')) return;
      var bar = document.createElement('div');
      bar.className = 'proof-help';
      var btn = document.createElement('button');
      btn.className = 'mviz-play';
      btn.textContent = 'Décortiquer avec Claude';
      btn.addEventListener('click', function (ev) {
        ev.preventDefault();
        var heading = d.getAttribute('data-of') || nearestHeading(d);
        if (bridge) bridge.openProofHelper(d.id, heading, d.innerText.slice(0, 6000));
      });
      bar.appendChild(btn);
      d.appendChild(bar);
      addBrouillonSwitch(d, sum);
    });
  }

  // Bascule « Preuve rédigée » / « Brouillon : comment on trouve », en haut de
  // la preuve. La barre reste au même endroit de l'écran : on ne perd pas sa
  // position en passant de l'un à l'autre.
  function addBrouillonSwitch(d, sum) {
    var key = d.getAttribute('data-brouillon');
    if (!key || !window.Brouillon || !window.Brouillon.eligible(key)) return;
    if (d.querySelector('.proof-switch')) return;
    var bar = document.createElement('div');
    bar.className = 'proof-switch';
    var proofBtn = document.createElement('button');
    proofBtn.type = 'button';
    proofBtn.className = 'on';
    proofBtn.textContent = 'Preuve rédigée';
    var draftBtn = document.createElement('button');
    draftBtn.type = 'button';
    draftBtn.textContent = 'Brouillon : comment on trouve';
    bar.appendChild(proofBtn);
    bar.appendChild(draftBtn);
    sum.parentNode.insertBefore(bar, sum.nextSibling);
    var pane = null;

    function show(draft) {
      var before = bar.getBoundingClientRect().top;
      if (draft && !pane) {
        try {
          pane = window.Brouillon.pane(key, bar);
        } catch (err) {
          if (window.console) console.error('brouillon : panneau', err);
          return;
        }
      }
      Array.prototype.forEach.call(d.children, function (c) {
        if (c === sum || c === bar || c === pane || c.classList.contains('proof-help')) return;
        c.style.display = draft ? 'none' : '';
      });
      if (pane) pane.style.display = draft ? '' : 'none';
      proofBtn.classList.toggle('on', !draft);
      draftBtn.classList.toggle('on', draft);
      window.scrollBy(0, bar.getBoundingClientRect().top - before);
    }
    proofBtn.addEventListener('click', function (ev) { ev.preventDefault(); show(false); });
    draftBtn.addEventListener('click', function (ev) { ev.preventDefault(); show(true); });
  }

  function nearestHeading(node) {
    var n = node;
    while (n) {
      var p = n.previousElementSibling;
      while (p) {
        if (/^H[1-4]$/.test(p.tagName)) return p.textContent.trim();
        p = p.previousElementSibling;
      }
      n = n.parentElement;
    }
    return document.title;
  }

  // ------------------------------------------------------------ selection
  function setupAsk() {
    var btn = document.createElement('button');
    btn.id = 'ask-bubble';
    btn.textContent = 'Demander à Claude';
    document.body.appendChild(btn);
    var pending = '';

    function hide() { btn.style.display = 'none'; }

    document.addEventListener('mouseup', function () {
      setTimeout(function () {
        var sel = window.getSelection();
        var text = sel ? String(sel).trim() : '';
        if (text.length < 3 || !sel.rangeCount) { hide(); return; }
        var rect = sel.getRangeAt(0).getBoundingClientRect();
        if (!rect || (!rect.width && !rect.height)) { hide(); return; }
        pending = text.slice(0, 4000);
        btn.style.display = 'block';
        var left = Math.min(Math.max(8, rect.left + rect.width / 2 - 70), window.innerWidth - 160);
        btn.style.left = left + 'px';
        btn.style.top = Math.max(8, rect.top - 42) + 'px';
      }, 10);
    });
    document.addEventListener('scroll', hide, { passive: true });
    document.addEventListener('mousedown', function (e) {
      if (e.target !== btn) hide();
    });
    btn.addEventListener('click', function () {
      if (bridge && pending) bridge.askAbout(pending, nearestHeadingFromSelection());
      hide();
    });

    function nearestHeadingFromSelection() {
      var sel = window.getSelection();
      if (!sel || !sel.rangeCount) return document.title;
      var node = sel.getRangeAt(0).startContainer;
      if (node.nodeType === 3) node = node.parentElement;
      return nearestHeading(node);
    }
  }

  // ------------------------------------------------------------- divers
  function wrapTables() {
    Array.prototype.forEach.call(document.querySelectorAll('article table'), function (t) {
      if (t.parentElement.classList.contains('table-scroll')) return;
      var w = document.createElement('div');
      w.className = 'table-scroll';
      t.parentNode.insertBefore(w, t);
      w.appendChild(t);
    });
  }

  function setupMasks() {
    Array.prototype.forEach.call(document.querySelectorAll('.mask'), function (m) {
      m.addEventListener('click', function () { m.classList.add('revealed'); });
    });
  }

  // Renvois vers un cours de l'application : <a class="course-ref" data-course="id">
  function setupCourseRefs() {
    document.addEventListener('click', function (ev) {
      var exo = ev.target && ev.target.closest ? ev.target.closest('a.exercise-ref') : null;
      if (exo) {
        ev.preventDefault();
        if (bridge && bridge.openExercise) bridge.openExercise(exo.getAttribute('data-exercise') || '');
        return;
      }
      var link = ev.target && ev.target.closest ? ev.target.closest('a.course-ref') : null;
      if (!link) return;
      ev.preventDefault();
      var id = link.getAttribute('data-course');
      var section = link.getAttribute('data-section') || '';
      if (!bridge || !id) return;
      if (section && bridge.openCourseAt) bridge.openCourseAt(id, section);
      else if (bridge.openCourse) bridge.openCourse(id);
    });
  }

  // Aller a une section d'apres son titre (liens des reponses aux questions).
  // Correspondance souple : les titres contiennent parfois des formules rendues.
  window.scrollToSection = function (title) {
    function norm(s) {
      return String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .replace(/[^a-z0-9]+/g, ' ').trim();
    }
    var want = norm(title), best = null, bestScore = 0;
    var words = want.split(' ').filter(function (w) { return w.length > 3; });
    Array.prototype.forEach.call(document.querySelectorAll('article h2, article h3'), function (h) {
      var got = norm(h.textContent), score = 0;
      if (got === want) score = 3;
      else if (want && (got.indexOf(want) >= 0 || want.indexOf(got) >= 0)) score = 2;
      else if (words.length) {
        var hits = words.filter(function (w) { return got.indexOf(w) >= 0; }).length;
        if (hits / words.length >= 0.6) score = 1 + hits / 100;
      }
      if (score > bestScore) { bestScore = score; best = h; }
    });
    if (!best) return false;
    window.scrollTo(0, best.getBoundingClientRect().top + window.scrollY - 60);
    best.classList.add('flash');
    setTimeout(function () { best.classList.remove('flash'); }, 1800);
    return true;
  };

  // ---------------------------------------------------- position de lecture
  // Section visible en haut de l'ecran (ancre et titre) et decalage relatif
  // dans cette section : un defilement en pixels ne survit ni a un
  // redimensionnement, ni au rendu des formules, ni au zoom.
  var READ_TOP = 80;
  var reading = null, saveTimer = null;

  function normText(s) {
    return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
      .replace(/[^a-z0-9]+/g, ' ').trim();
  }
  function readingHeads() {
    return Array.prototype.slice.call(document.querySelectorAll('article h2, article h3'));
  }
  function absTop(el) { return el.getBoundingClientRect().top + window.scrollY; }
  function pageHeight() { return document.documentElement.scrollHeight; }

  function currentPosition() {
    var heads = readingHeads();
    if (!heads.length) return null;
    var y = window.scrollY + READ_TOP, at = 0;
    for (var i = 0; i < heads.length; i++) {
      if (absTop(heads[i]) <= y) at = i; else break;
    }
    var h = heads[at], start = absTop(h);
    var end = at + 1 < heads.length ? absTop(heads[at + 1]) : pageHeight();
    var max = pageHeight() - window.innerHeight;
    return {
      course: reading ? reading.course : '',
      sectionId: h.id || '', title: h.textContent.trim().slice(0, 300), index: at,
      offset: Math.max(0, Math.min(1, end > start ? (y - start) / (end - start) : 0)),
      fraction: max > 0 ? Math.max(0, Math.min(1, window.scrollY / max)) : 0
    };
  }

  function saveReading() {
    saveTimer = null;
    if (!reading || !bridge || !bridge.saveReadingPosition) return;
    var pos = currentPosition();
    if (pos) bridge.saveReadingPosition(JSON.stringify(pos));
  }

  // Section enregistree : meme ancre et meme titre, sinon meme titre (cours
  // regenere), sinon rien et l'on reste au debut.
  function findHeading(pos) {
    if (!pos) return null;
    var heads = readingHeads(), want = normText(pos.section_title || pos.title);
    if (!want) return null;
    var id = pos.section_id || pos.sectionId;
    var byId = id ? document.getElementById(id) : null;
    if (byId && heads.indexOf(byId) >= 0 && normText(byId.textContent) === want) return byId;
    var same = heads.filter(function (h) { return normText(h.textContent) === want; });
    if (!same.length) return null;
    var index = pos.section_index != null ? pos.section_index : (pos.index || 0);
    same.sort(function (a, b) {
      return Math.abs(heads.indexOf(a) - index) - Math.abs(heads.indexOf(b) - index);
    });
    return same[0];
  }

  function goToPosition(pos) {
    var h = findHeading(pos);
    if (!h) return false;
    var heads = readingHeads(), i = heads.indexOf(h), start = absTop(h);
    var end = i + 1 < heads.length ? absTop(heads[i + 1]) : pageHeight();
    var offset = pos.section_offset != null ? pos.section_offset : (pos.offset || 0);
    window.scrollTo({ top: Math.max(0, start + offset * (end - start) - READ_TOP),
                      left: 0, behavior: 'instant' });
    return true;
  }

  // Apres les formules, les polices et les images : sinon la section bouge encore.
  function whenRendered(fn) {
    var done = false, pending = 1;
    function finish() { if (!done) { done = true; setTimeout(fn, 60); } }
    function one() { if (--pending <= 0) finish(); }
    Array.prototype.forEach.call(document.images, function (im) {
      if (im.complete) return;
      pending++;
      im.addEventListener('load', one, { once: true });
      im.addEventListener('error', one, { once: true });
    });
    (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(one, one);
    setTimeout(finish, 3000);
  }

  function removeBanner() {
    var old = document.getElementById('resume-banner');
    if (old) old.remove();
  }

  function resumeAt(pos) {
    removeBanner();
    whenRendered(function () {
      if (!goToPosition(pos)) return;
      // les figures se dessinent apres coup : on corrige une fois
      setTimeout(function () { goToPosition(pos); }, 350);
    });
  }

  function showResumeBanner(pos, heading) {
    removeBanner();
    var bar = document.createElement('div');
    bar.id = 'resume-banner';
    var go = document.createElement('button');
    go.className = 'resume-go';
    go.title = 'Revenir où vous en étiez';
    go.innerHTML = '<b>Reprendre à :</b> ';
    var name = document.createElement('span');
    name.innerHTML = heading.innerHTML;   // formules deja rendues
    go.appendChild(name);
    go.addEventListener('click', function () { resumeAt(pos); });
    var close = document.createElement('button');
    close.className = 'resume-close';
    close.title = 'Ignorer';
    close.textContent = '×';
    close.addEventListener('click', removeBanner);
    bar.appendChild(go);
    bar.appendChild(close);
    document.body.appendChild(bar);
    // disparait au premier defilement manuel
    var startY = window.scrollY;
    function onScroll() {
      if (!document.getElementById('resume-banner')) {
        window.removeEventListener('scroll', onScroll);
      } else if (Math.abs(window.scrollY - startY) > 30) {
        window.removeEventListener('scroll', onScroll);
        removeBanner();
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true });
  }

  /* Appele par l'application une fois la page chargee : suit la lecture du
     cours `course` et propose de reprendre a `saved` (ou y va si `autoResume`). */
  window.initReading = function (course, saved, autoResume) {
    var first = !reading;
    reading = { course: course };
    if (first) {
      window.addEventListener('scroll', function () {
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(saveReading, 1000);
      }, { passive: true });
      window.addEventListener('pagehide', window.readingFlush);
    }
    removeBanner();
    var heading = findHeading(saved);
    if (!heading) return false;
    if (autoResume) resumeAt(saved);
    else showResumeBanner(saved, heading);
    return true;
  };

  window.resumeReading = function (saved) {
    if (!findHeading(saved)) return false;
    resumeAt(saved);
    return true;
  };

  window.readingFlush = function () {
    if (saveTimer) { clearTimeout(saveTimer); saveReading(); }
  };

  window.readingPosition = function () { return currentPosition(); };

  window.setTheme = function (name) {
    document.documentElement.setAttribute('data-theme', name);
    window.dispatchEvent(new Event('mviz:theme'));
  };

  window.scrollToHeading = function (text) {
    var heads = document.querySelectorAll('article h2, article h3');
    for (var i = 0; i < heads.length; i++) {
      if (heads[i].textContent.indexOf(text) !== -1) {
        heads[i].scrollIntoView({ behavior: 'smooth', block: 'start' });
        return true;
      }
    }
    return false;
  };

  function boot() {
    wrapTables();
    buildToc();
    renderMath();
    if (window.Brouillon) window.Brouillon.typeset = renderMathIn;
    decorateProofs();
    setupMasks();
    setupCourseRefs();
    connectBridge(setupAsk);
    // Les figures sont dessinees apres KaTeX pour avoir la bonne largeur.
    window.dispatchEvent(new Event('mviz:theme'));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
