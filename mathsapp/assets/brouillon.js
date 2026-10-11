/* Brouillons des démonstrations : « comment on trouve » la preuve.
   Partagé par la page de cours et la page des démonstrations. L'état vient de
   window.BROUILLONS ({clé: {eligible, status, html, trivial}}), joint par
   l'application ; elle le met à jour par window.setBrouillon. */
(function () {
  'use strict';

  var PENDING = {}, ERRORS = {};

  var css = document.createElement('style');
  css.textContent = [
    '.proof-switch { display:flex; gap:6px; margin:6px 0 10px; }',
    '.proof-switch button, .brouillon-pane button {',
    '  font: 600 12.5px ui-sans-serif, system-ui, sans-serif; padding:4px 11px;',
    '  border-radius:8px; border:1px solid var(--line-strong); background:var(--bg-soft);',
    '  color:var(--fg); cursor:pointer; }',
    '.proof-switch button.on { background:var(--accent-soft); border-color:var(--accent); color:var(--accent); }',
    '.brouillon-pane { border-left:3px dashed var(--warn); padding:4px 0 4px 14px; margin:6px 0 10px; }',
    '.brouillon-pane h4 { margin:14px 0 4px; font-size:.95em; }',
    '.brouillon-pane .bnote { color:var(--muted); font-size:.92em; }',
    '.brouillon-pane .bwarn { background:var(--warn-soft); border-radius:7px; padding:7px 10px; margin:6px 0; font-size:.92em; }',
    '.brouillon-pane .brow { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }'
  ].join('\n');
  (document.head || document.documentElement).appendChild(css);

  function data() { return window.BROUILLONS || (window.BROUILLONS = {}); }
  function app() { return window.app || null; }

  function button(label, onClick) {
    var b = document.createElement('button');
    b.type = 'button';
    b.textContent = label;
    b.addEventListener('click', function (ev) { ev.preventDefault(); onClick(); });
    return b;
  }

  function request(key) {
    if (!app() || !app().generateBrouillon) return;
    PENDING[key] = true;
    delete ERRORS[key];
    app().generateBrouillon(key);
    refresh(key);
  }

  function requestAll() {
    if (!app() || !app().generateBrouillon) return;
    var d = data();
    Object.keys(d).forEach(function (k) {
      if (d[k].eligible && d[k].status !== 'ok') { PENDING[k] = true; delete ERRORS[k]; }
    });
    app().generateBrouillon('*');
    refreshAll();
  }

  /* Remplit un panneau de brouillon selon l'état de la clé. */
  function render(pane, key) {
    var st = data()[key] || { status: 'missing' };
    pane.innerHTML = '';
    if (ERRORS[key]) {
      var err = document.createElement('div');
      err.className = 'bwarn';
      err.textContent = 'La génération du brouillon a échoué : ' + ERRORS[key];
      pane.appendChild(err);
    }
    if (PENDING[key]) {
      var wait = document.createElement('p');
      wait.className = 'bnote';
      wait.textContent = 'Brouillon en cours de génération… L\'avancement est visible '
        + 'dans la file de génération (Ctrl+G).';
      pane.appendChild(wait);
      return;
    }
    var row = document.createElement('div');
    row.className = 'brow';
    if (st.status === 'missing') {
      var intro = document.createElement('p');
      intro.className = 'bnote';
      intro.textContent = 'Le brouillon montre comment on trouve cette preuve : point de '
        + 'départ, idée directrice, choix clés faits à rebours, tentative naïve, lien avec '
        + 'chaque étape de la preuve rédigée. Il n\'est produit qu\'à la demande.';
      pane.appendChild(intro);
      row.appendChild(button(ERRORS[key] ? 'Relancer' : 'Générer le brouillon',
                             function () { request(key); }));
      row.appendChild(button('Générer les brouillons de toutes les démonstrations de ce cours',
                             requestAll));
      pane.appendChild(row);
      return;
    }
    if (st.status === 'obsolete') {
      var old = document.createElement('div');
      old.className = 'bwarn';
      old.textContent = 'Obsolète : ce brouillon a été écrit pour une version antérieure de '
        + 'la démonstration. Régénérez-le pour qu\'il colle à la preuve actuelle.';
      pane.appendChild(old);
    }
    if (st.trivial) {
      var tri = document.createElement('p');
      tri.className = 'bnote';
      tri.textContent = 'Démonstration directe : il n\'y a guère de choix à expliquer.';
      pane.appendChild(tri);
    }
    var body = document.createElement('div');
    body.innerHTML = st.html || '';
    pane.appendChild(body);
    row.appendChild(button(ERRORS[key] ? 'Relancer' : 'Régénérer le brouillon',
                           function () { request(key); }));
    pane.appendChild(row);
    // une formule mal formée ne doit pas empêcher d'afficher le brouillon
    try {
      if (window.Brouillon.typeset) window.Brouillon.typeset(pane);
    } catch (err) {
      if (window.console) console.error('brouillon : rendu des formules', err);
    }
  }

  function panes(key) {
    return Array.prototype.filter.call(document.querySelectorAll('.brouillon-pane'),
      function (p) { return !key || p.getAttribute('data-key') === key; });
  }
  function refresh(key) { panes(key).forEach(function (p) { render(p, key); }); }
  function refreshAll() {
    panes('').forEach(function (p) { render(p, p.getAttribute('data-key')); });
  }

  window.Brouillon = {
    typeset: null,
    data: data,
    render: render,
    request: request,
    /* Démonstration qui mérite un brouillon (pas une preuve d'une ligne). */
    eligible: function (key) { var st = data()[key]; return !!(st && st.eligible); },
    /* Panneau inséré dans la page (après `after`, ou dans `host`), puis rendu :
       les formules se composent dans le document, pas dans un nœud détaché. */
    pane: function (key, after, host) {
      var p = document.createElement('div');
      p.className = 'brouillon-pane';
      p.setAttribute('data-key', key);
      if (after) after.parentNode.insertBefore(p, after.nextSibling);
      else if (host) host.appendChild(p);
      render(p, key);
      return p;
    }
  };

  /* Appelés par l'application. */
  window.setBrouillon = function (key, state) {
    var before = JSON.stringify(data()[key] || null);
    data()[key] = state;
    if (state && state.status === 'ok') {
      // produit : plus d'attente ni d'erreur ; sinon l'attente se poursuit
      var changed = PENDING[key] || ERRORS[key] || before !== JSON.stringify(state);
      delete PENDING[key];
      delete ERRORS[key];
      if (changed) refresh(key);
    }
  };
  window.brouillonPending = function (key) {
    if (key === '*') {
      var d = data();
      Object.keys(d).forEach(function (k) {
        if (d[k].eligible && d[k].status !== 'ok' && !PENDING[k]) {
          PENDING[k] = true;
          refresh(k);
        }
      });
      return;
    }
    if (!PENDING[key]) { PENDING[key] = true; refresh(key); }
  };
  /* Échec (ou annulation) : clé précise, ou « * » pour toutes celles en attente. */
  window.brouillonFailed = function (key, message) {
    Object.keys(PENDING).forEach(function (k) {
      if (key === '*' || k === key) {
        delete PENDING[k];
        if (message) ERRORS[k] = message;
        refresh(k);
      }
    });
  };
})();
