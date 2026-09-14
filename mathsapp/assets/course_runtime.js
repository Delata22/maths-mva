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
  function renderMath() {
    if (typeof renderMathInElement === 'undefined') return;
    renderMathInElement(document.body, {
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
    });
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
      var link = ev.target && ev.target.closest ? ev.target.closest('a.course-ref') : null;
      if (!link) return;
      ev.preventDefault();
      var id = link.getAttribute('data-course');
      if (bridge && id && bridge.openCourse) bridge.openCourse(id);
    });
  }

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
