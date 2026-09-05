/* mviz - petite bibliotheque de figures mathematiques interactives.
   Concue pour etre ecrite a la main par un modele : une seule fonction
   d'entree, des primitives en coordonnees mathematiques, des curseurs
   automatiques. Aucune dependance. */
(function (global) {
  'use strict';

  var PALETTE = {
    accent: '#2f6df6', accent2: '#e0562f', ok: '#10a37f', warn: '#d97706',
    violet: '#7c4dff', pink: '#db2777', teal: '#0d9488', muted: '#8a93a6',
    fg: '#1a1d24', grid: '#dfe3ec', axis: '#9aa3b2', bg: '#ffffff'
  };
  var DARK = {
    accent: '#6ea0ff', accent2: '#ff8f6b', ok: '#3ddc97', warn: '#fbbf24',
    violet: '#b39dff', pink: '#f472b6', teal: '#2dd4bf', muted: '#8b93a5',
    fg: '#e6e9f0', grid: '#2a3040', axis: '#5b6478', bg: '#12151c'
  };

  function isDark() {
    return document.documentElement.getAttribute('data-theme') === 'dark';
  }
  function pal() { return isDark() ? DARK : PALETTE; }
  function color(c) {
    if (!c) return pal().accent;
    return pal()[c] || c;
  }

  function el(tag, cls, parent) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (parent) parent.appendChild(n);
    return n;
  }

  function resolve(target) {
    if (typeof target === 'string') {
      var found = document.querySelector(target);
      if (!found) throw new Error('mviz: cible introuvable ' + target);
      return found;
    }
    return target;
  }

  // ------------------------------------------------------------------ Canvas
  function Ctx(canvas, opts) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.opts = opts;
    this.pad = opts.pad || { l: 46, r: 16, t: 16, b: 34 };
  }

  Ctx.prototype.resize = function (w, h) {
    var dpr = global.devicePixelRatio || 1;
    this.w = w; this.h = h;
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.canvas.style.width = w + 'px';
    this.canvas.style.height = h + 'px';
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };

  Ctx.prototype.setRange = function (xr, yr) { this.xr = xr; this.yr = yr; };

  Ctx.prototype.X = function (x) {
    var p = this.pad;
    return p.l + (x - this.xr[0]) / (this.xr[1] - this.xr[0]) * (this.w - p.l - p.r);
  };
  Ctx.prototype.Y = function (y) {
    var p = this.pad;
    return this.h - p.b - (y - this.yr[0]) / (this.yr[1] - this.yr[0]) * (this.h - p.t - p.b);
  };
  Ctx.prototype.invX = function (px) {
    var p = this.pad;
    return this.xr[0] + (px - p.l) / (this.w - p.l - p.r) * (this.xr[1] - this.xr[0]);
  };
  Ctx.prototype.invY = function (py) {
    var p = this.pad;
    return this.yr[0] + (this.h - p.b - py) / (this.h - p.t - p.b) * (this.yr[1] - this.yr[0]);
  };

  Ctx.prototype.clear = function () {
    this.ctx.clearRect(0, 0, this.w, this.h);
  };

  function niceStep(span, target) {
    var raw = span / (target || 8);
    var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var norm = raw / mag;
    var step = norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10;
    return step * mag;
  }

  function fmt(v, step) {
    if (Math.abs(v) < 1e-12) return '0';
    var dec = Math.max(0, -Math.floor(Math.log(step) / Math.LN10));
    return v.toFixed(Math.min(dec, 4)).replace(/\.?0+$/, '');
  }

  Ctx.prototype.grid = function () {
    var c = this.ctx, p = pal();
    var sx = niceStep(this.xr[1] - this.xr[0], this.w / 90);
    var sy = niceStep(this.yr[1] - this.yr[0], this.h / 60);
    c.save();
    c.lineWidth = 1;
    c.strokeStyle = p.grid;
    c.fillStyle = p.muted;
    c.font = '11px ui-sans-serif, system-ui, sans-serif';
    c.textAlign = 'center'; c.textBaseline = 'top';
    for (var x = Math.ceil(this.xr[0] / sx) * sx; x <= this.xr[1] + 1e-9; x += sx) {
      c.beginPath(); c.moveTo(this.X(x), this.pad.t); c.lineTo(this.X(x), this.h - this.pad.b); c.stroke();
      if (this.opts.ticks !== false) c.fillText(fmt(x, sx), this.X(x), this.h - this.pad.b + 6);
    }
    c.textAlign = 'right'; c.textBaseline = 'middle';
    for (var y = Math.ceil(this.yr[0] / sy) * sy; y <= this.yr[1] + 1e-9; y += sy) {
      c.beginPath(); c.moveTo(this.pad.l, this.Y(y)); c.lineTo(this.w - this.pad.r, this.Y(y)); c.stroke();
      if (this.opts.ticks !== false) c.fillText(fmt(y, sy), this.pad.l - 7, this.Y(y));
    }
    c.restore();
  };

  Ctx.prototype.axes = function () {
    var c = this.ctx, p = pal();
    c.save();
    c.strokeStyle = p.axis; c.lineWidth = 1.4;
    if (this.yr[0] <= 0 && this.yr[1] >= 0) {
      c.beginPath(); c.moveTo(this.pad.l, this.Y(0)); c.lineTo(this.w - this.pad.r, this.Y(0)); c.stroke();
    }
    if (this.xr[0] <= 0 && this.xr[1] >= 0) {
      c.beginPath(); c.moveTo(this.X(0), this.pad.t); c.lineTo(this.X(0), this.h - this.pad.b); c.stroke();
    }
    c.fillStyle = p.muted;
    c.font = '12px ui-sans-serif, system-ui, sans-serif';
    if (this.opts.xlabel) {
      c.textAlign = 'right'; c.textBaseline = 'bottom';
      c.fillText(this.opts.xlabel, this.w - this.pad.r, this.h - 4);
    }
    if (this.opts.ylabel) {
      c.textAlign = 'left'; c.textBaseline = 'top';
      c.fillText(this.opts.ylabel, 4, 2);
    }
    c.restore();
  };

  // ------------------------------------------------------------- primitives
  function G(cx) { this.c = cx; this._legend = []; }

  G.prototype._stroke = function (o) {
    var c = this.c.ctx;
    c.lineWidth = (o && o.width) || 2.2;
    c.strokeStyle = color(o && o.color);
    c.setLineDash((o && o.dash) ? (Array.isArray(o.dash) ? o.dash : [6, 5]) : []);
    c.lineJoin = 'round'; c.lineCap = 'round';
    if (o && o.alpha != null) c.globalAlpha = o.alpha;
  };
  G.prototype._reset = function () {
    this.c.ctx.globalAlpha = 1; this.c.ctx.setLineDash([]);
  };

  /** courbe y = f(x) */
  G.prototype.curve = function (f, o) {
    o = o || {};
    var cx = this.c, c = cx.ctx;
    var n = o.samples || 600, started = false;
    c.save(); this._stroke(o); c.beginPath();
    for (var i = 0; i <= n; i++) {
      var x = cx.xr[0] + (cx.xr[1] - cx.xr[0]) * i / n;
      var y = f(x);
      if (!isFinite(y) || y > cx.yr[1] + 1e4 || y < cx.yr[0] - 1e4) { started = false; continue; }
      var px = cx.X(x), py = cx.Y(y);
      if (!started) { c.moveTo(px, py); started = true; } else { c.lineTo(px, py); }
    }
    c.stroke(); c.restore(); this._reset();
    if (o.label) this._legend.push({ label: o.label, color: color(o.color), dash: !!o.dash });
    return this;
  };

  /** courbe parametree t -> [x, y] */
  G.prototype.param = function (f, trange, o) {
    o = o || {};
    var cx = this.c, c = cx.ctx, n = o.samples || 600;
    c.save(); this._stroke(o); c.beginPath();
    for (var i = 0; i <= n; i++) {
      var t = trange[0] + (trange[1] - trange[0]) * i / n;
      var pt = f(t);
      if (!pt || !isFinite(pt[0]) || !isFinite(pt[1])) continue;
      var px = cx.X(pt[0]), py = cx.Y(pt[1]);
      if (i === 0) c.moveTo(px, py); else c.lineTo(px, py);
    }
    c.stroke(); c.restore(); this._reset();
    if (o.label) this._legend.push({ label: o.label, color: color(o.color), dash: !!o.dash });
    return this;
  };

  /** ligne brisee a partir d'une liste de points [[x,y], ...] */
  G.prototype.polyline = function (pts, o) {
    o = o || {};
    var cx = this.c, c = cx.ctx;
    if (!pts.length) return this;
    c.save(); this._stroke(o); c.beginPath();
    c.moveTo(cx.X(pts[0][0]), cx.Y(pts[0][1]));
    for (var i = 1; i < pts.length; i++) c.lineTo(cx.X(pts[i][0]), cx.Y(pts[i][1]));
    if (o.close) c.closePath();
    if (o.fill) { c.fillStyle = color(o.fill); c.globalAlpha = o.fillAlpha == null ? 0.18 : o.fillAlpha; c.fill(); c.globalAlpha = 1; }
    if (o.stroke !== false) c.stroke();
    c.restore(); this._reset();
    if (o.label) this._legend.push({ label: o.label, color: color(o.color), dash: !!o.dash });
    return this;
  };

  G.prototype.segment = function (a, b, o) { return this.polyline([a, b], o); };

  G.prototype.hline = function (y, o) {
    return this.polyline([[this.c.xr[0], y], [this.c.xr[1], y]], Object.assign({ color: 'muted', width: 1.4, dash: true }, o || {}));
  };
  G.prototype.vline = function (x, o) {
    return this.polyline([[x, this.c.yr[0]], [x, this.c.yr[1]]], Object.assign({ color: 'muted', width: 1.4, dash: true }, o || {}));
  };

  G.prototype.point = function (x, y, o) {
    o = o || {};
    var cx = this.c, c = cx.ctx;
    c.save();
    c.fillStyle = color(o.color || 'accent2');
    c.beginPath(); c.arc(cx.X(x), cx.Y(y), o.r || 4.5, 0, 6.2832); c.fill();
    if (o.ring) { c.strokeStyle = pal().bg; c.lineWidth = 2; c.stroke(); }
    if (o.label) {
      c.fillStyle = pal().fg;
      c.font = (o.font || '12px') + ' ui-sans-serif, system-ui, sans-serif';
      c.textAlign = o.align || 'left'; c.textBaseline = 'bottom';
      c.fillText(o.label, cx.X(x) + (o.align === 'right' ? -8 : 8), cx.Y(y) - 6);
    }
    c.restore();
    return this;
  };

  /** vecteur (fleche) de a vers b */
  G.prototype.vector = function (a, b, o) {
    o = o || {};
    var cx = this.c, c = cx.ctx;
    var x1 = cx.X(a[0]), y1 = cx.Y(a[1]), x2 = cx.X(b[0]), y2 = cx.Y(b[1]);
    var ang = Math.atan2(y2 - y1, x2 - x1), head = o.head || 9;
    c.save(); this._stroke(o);
    c.beginPath(); c.moveTo(x1, y1); c.lineTo(x2, y2); c.stroke();
    c.fillStyle = color(o.color);
    c.beginPath();
    c.moveTo(x2, y2);
    c.lineTo(x2 - head * Math.cos(ang - 0.4), y2 - head * Math.sin(ang - 0.4));
    c.lineTo(x2 - head * Math.cos(ang + 0.4), y2 - head * Math.sin(ang + 0.4));
    c.closePath(); c.fill();
    if (o.label) {
      c.fillStyle = pal().fg;
      c.font = '12px ui-sans-serif, system-ui, sans-serif';
      c.textAlign = 'left'; c.textBaseline = 'bottom';
      c.fillText(o.label, x2 + 6, y2 - 4);
    }
    c.restore(); this._reset();
    if (o.label && o.legend) this._legend.push({ label: o.label, color: color(o.color) });
    return this;
  };

  /** aire entre deux courbes sur [a, b] */
  G.prototype.area = function (f, g, range, o) {
    o = o || {};
    var cx = this.c, c = cx.ctx, n = o.samples || 300;
    var a = range[0], b = range[1];
    var lower = typeof g === 'function' ? g : function () { return g || 0; };
    c.save();
    c.fillStyle = color(o.color || 'accent');
    c.globalAlpha = o.alpha == null ? 0.16 : o.alpha;
    c.beginPath();
    for (var i = 0; i <= n; i++) {
      var x = a + (b - a) * i / n;
      c[i ? 'lineTo' : 'moveTo'](cx.X(x), cx.Y(f(x)));
    }
    for (var j = n; j >= 0; j--) {
      var x2 = a + (b - a) * j / n;
      c.lineTo(cx.X(x2), cx.Y(lower(x2)));
    }
    c.closePath(); c.fill(); c.restore();
    return this;
  };

  /** rectangles (sommes de Riemann, histogrammes) */
  G.prototype.bars = function (items, o) {
    o = o || {};
    var cx = this.c, c = cx.ctx;
    c.save();
    items.forEach(function (it) {
      var x0 = cx.X(it[0]), x1 = cx.X(it[1]), y0 = cx.Y(0), y1 = cx.Y(it[2]);
      c.fillStyle = color(it[3] || o.color || 'accent');
      c.globalAlpha = o.alpha == null ? 0.35 : o.alpha;
      c.fillRect(x0, Math.min(y0, y1), x1 - x0, Math.abs(y1 - y0));
      c.globalAlpha = 1;
      c.strokeStyle = color(it[3] || o.color || 'accent');
      c.lineWidth = 1;
      c.strokeRect(x0, Math.min(y0, y1), x1 - x0, Math.abs(y1 - y0));
    });
    c.restore();
    return this;
  };

  G.prototype.text = function (x, y, s, o) {
    o = o || {};
    var cx = this.c, c = cx.ctx;
    c.save();
    c.fillStyle = color(o.color || 'fg');
    c.font = (o.size || 12) + 'px ui-sans-serif, system-ui, sans-serif';
    c.textAlign = o.align || 'left';
    c.textBaseline = o.baseline || 'middle';
    c.fillText(s, cx.X(x) + (o.dx || 0), cx.Y(y) + (o.dy || 0));
    c.restore();
    return this;
  };

  /** carte de couleur d'un champ scalaire f(x, y) */
  G.prototype.heat = function (f, o) {
    o = o || {};
    var cx = this.c, c = cx.ctx;
    var p = cx.pad;
    var w = Math.max(1, Math.round(cx.w - p.l - p.r));
    var h = Math.max(1, Math.round(cx.h - p.t - p.b));
    var step = o.step || 2;
    var vals = [], min = Infinity, max = -Infinity;
    for (var py = 0; py < h; py += step) {
      var row = [];
      for (var px = 0; px < w; px += step) {
        var v = f(cx.invX(px + p.l), cx.invY(py + p.t));
        if (!isFinite(v)) v = NaN;
        if (v < min) min = v; if (v > max) max = v;
        row.push(v);
      }
      vals.push(row);
    }
    if (o.min != null) min = o.min;
    if (o.max != null) max = o.max;
    var dark = isDark();
    c.save();
    for (var i = 0; i < vals.length; i++) {
      for (var j = 0; j < vals[i].length; j++) {
        var t = (vals[i][j] - min) / (max - min || 1);
        if (!isFinite(t)) continue;
        t = Math.max(0, Math.min(1, o.log ? Math.log1p(9 * t) / Math.LN10 : t));
        var l = dark ? (14 + 46 * (1 - t)) : (100 - 42 * t);
        var hue = o.hue == null ? 220 : o.hue;
        c.fillStyle = 'hsl(' + hue + ',' + (18 + 52 * (1 - t)) + '%,' + l + '%)';
        c.fillRect(p.l + j * step, p.t + i * step, step, step);
      }
    }
    c.restore();
    return this;
  };

  /** lignes de niveau de f par marching squares */
  G.prototype.contour = function (f, levels, o) {
    o = o || {};
    var cx = this.c, c = cx.ctx;
    var n = o.res || 90;
    var x0 = cx.xr[0], x1 = cx.xr[1], y0 = cx.yr[0], y1 = cx.yr[1];
    var dx = (x1 - x0) / n, dy = (y1 - y0) / n;
    var grid = [];
    for (var i = 0; i <= n; i++) {
      grid[i] = [];
      for (var j = 0; j <= n; j++) grid[i][j] = f(x0 + j * dx, y0 + i * dy);
    }
    c.save();
    c.lineWidth = o.width || 1.3;
    c.strokeStyle = color(o.color || 'axis');
    if (o.alpha != null) c.globalAlpha = o.alpha;
    levels.forEach(function (lv) {
      c.beginPath();
      for (var i = 0; i < n; i++) {
        for (var j = 0; j < n; j++) {
          var a = grid[i][j], b = grid[i][j + 1], d = grid[i + 1][j + 1], e = grid[i + 1][j];
          var xa = x0 + j * dx, xb = xa + dx, ya = y0 + i * dy, yb = ya + dy;
          var pts = [];
          function interp(p1, v1, p2, v2) {
            var t = (lv - v1) / (v2 - v1);
            return [p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])];
          }
          if ((a < lv) !== (b < lv)) pts.push(interp([xa, ya], a, [xb, ya], b));
          if ((b < lv) !== (d < lv)) pts.push(interp([xb, ya], b, [xb, yb], d));
          if ((d < lv) !== (e < lv)) pts.push(interp([xb, yb], d, [xa, yb], e));
          if ((e < lv) !== (a < lv)) pts.push(interp([xa, yb], e, [xa, ya], a));
          for (var k = 0; k + 1 < pts.length; k += 2) {
            c.moveTo(cx.X(pts[k][0]), cx.Y(pts[k][1]));
            c.lineTo(cx.X(pts[k + 1][0]), cx.Y(pts[k + 1][1]));
          }
        }
      }
      c.stroke();
    });
    c.restore(); this._reset();
    return this;
  };

  /** champ de vecteurs v(x, y) -> [vx, vy] */
  G.prototype.field = function (v, o) {
    o = o || {};
    var cx = this.c, n = o.n || 14, scale = o.scale || 0.6;
    var self = this;
    for (var i = 0; i <= n; i++) {
      for (var j = 0; j <= n; j++) {
        var x = cx.xr[0] + (cx.xr[1] - cx.xr[0]) * i / n;
        var y = cx.yr[0] + (cx.yr[1] - cx.yr[0]) * j / n;
        var w = v(x, y);
        if (!w || !isFinite(w[0]) || !isFinite(w[1])) continue;
        var norm = Math.hypot(w[0], w[1]) || 1;
        var unit = (cx.xr[1] - cx.xr[0]) / n * scale;
        self.vector([x, y], [x + w[0] / norm * unit, y + w[1] / norm * unit],
          { color: o.color || 'muted', width: 1.2, head: 5, alpha: o.alpha == null ? 0.75 : o.alpha });
      }
    }
    return this;
  };

  G.prototype.legend = function (entries) {
    var items = entries || this._legend;
    if (!items || !items.length) return this;
    var cx = this.c, c = cx.ctx;
    c.save();
    c.font = '12px ui-sans-serif, system-ui, sans-serif';
    var w = 0;
    items.forEach(function (it) { w = Math.max(w, c.measureText(it.label).width); });
    var bw = w + 40, bh = items.length * 19 + 10;
    var bx = cx.w - cx.pad.r - bw - 4, by = cx.pad.t + 4;
    c.fillStyle = isDark() ? 'rgba(18,21,28,.85)' : 'rgba(255,255,255,.85)';
    c.strokeStyle = pal().grid;
    c.lineWidth = 1;
    c.beginPath(); c.roundRect(bx, by, bw, bh, 6); c.fill(); c.stroke();
    items.forEach(function (it, k) {
      var yy = by + 15 + k * 19;
      c.strokeStyle = it.color; c.lineWidth = 2.4;
      c.setLineDash(it.dash ? [5, 4] : []);
      c.beginPath(); c.moveTo(bx + 10, yy); c.lineTo(bx + 28, yy); c.stroke();
      c.setLineDash([]);
      c.fillStyle = pal().fg; c.textAlign = 'left'; c.textBaseline = 'middle';
      c.fillText(it.label, bx + 34, yy);
    });
    c.restore();
    return this;
  };

  // --------------------------------------------------------------- figure
  /**
   * mviz.plot(cible, options)
   * options : xrange, yrange, width, height, xlabel, ylabel, grid, axes,
   *           equal (repere orthonorme), caption,
   *           params : { nom: {min, max, step, value, label} },
   *           animate : { param: 'nom', period: 4 }  (boucle automatique)
   *           draw(g, p) : fonction de dessin, p contient les valeurs des curseurs
   */
  function digitsOf(spec) {
    if (spec.digits != null) return spec.digits;
    var step = spec.step;
    if (step == null) return 2;
    if (step >= 1) return 0;
    return Math.min(4, Math.max(0, Math.ceil(-Math.log(step) / Math.LN10)));
  }

  function plot(target, opts) {
    opts = opts || {};
    var host = resolve(target);
    host.classList.add('mviz');
    host.innerHTML = '';

    var stage = el('div', 'mviz-stage', host);
    var canvas = el('canvas', null, stage);
    var controls = null;
    var params = opts.params || {};
    var values = {};
    Object.keys(params).forEach(function (k) {
      values[k] = params[k].value == null ? params[k].min : params[k].value;
    });

    var cx = new Ctx(canvas, opts);
    var api = null;

    function render() {
      var w = opts.width || Math.max(280, host.clientWidth || 640);
      var h = opts.height || Math.round(w * (opts.ratio || 0.58));
      cx.resize(w, h);
      var xr = (opts.xrange || [-5, 5]).slice();
      var yr = (opts.yrange || [-3, 3]).slice();
      if (opts.equal) {
        var p = cx.pad;
        var pw = w - p.l - p.r, ph = h - p.t - p.b;
        var sx = (xr[1] - xr[0]) / pw, sy = (yr[1] - yr[0]) / ph;
        var s = Math.max(sx, sy);
        var cxm = (xr[0] + xr[1]) / 2, cym = (yr[0] + yr[1]) / 2;
        xr = [cxm - s * pw / 2, cxm + s * pw / 2];
        yr = [cym - s * ph / 2, cym + s * ph / 2];
      }
      cx.setRange(xr, yr);
      cx.clear();
      if (opts.grid !== false) cx.grid();
      if (opts.axes !== false) cx.axes();
      api = new G(cx);
      try {
        opts.draw(api, values, cx);
      } catch (err) {
        var c = cx.ctx;
        c.fillStyle = '#dc2626';
        c.font = '12px ui-monospace, monospace';
        c.fillText('erreur de dessin : ' + err.message, 12, 20);
        if (global.console) console.error(err);
      }
      if (opts.legend !== false) api.legend();
    }

    var keys = Object.keys(params);
    if (keys.length) {
      controls = el('div', 'mviz-controls', host);
      keys.forEach(function (k) {
        var spec = params[k];
        var row = el('label', 'mviz-slider', controls);
        var name = el('span', 'mviz-slider-name', row);
        name.innerHTML = spec.label || k;
        var input = el('input', null, row);
        input.type = 'range';
        input.min = spec.min; input.max = spec.max;
        input.step = spec.step == null ? (spec.max - spec.min) / 100 : spec.step;
        input.value = values[k];
        var out = el('span', 'mviz-slider-value', row);
        out.textContent = (+values[k]).toFixed(digitsOf(spec));
        input.addEventListener('input', function () {
          values[k] = parseFloat(input.value);
          out.textContent = values[k].toFixed(digitsOf(spec));
          render();
        });
        row._input = input; row._out = out;
        params[k]._row = row;
      });
    }

    if (opts.caption) {
      var cap = el('figcaption', 'mviz-caption', host);
      cap.innerHTML = opts.caption;
    }

    if (opts.animate) {
      var spec = params[opts.animate.param];
      var bar = controls || el('div', 'mviz-controls', host);
      var btn = el('button', 'mviz-play', bar);
      btn.textContent = 'Lancer l\'animation';
      var running = false, raf = null, t0 = 0;
      var period = (opts.animate.period || 5) * 1000;
      function frame(ts) {
        if (!running) return;
        if (!t0) t0 = ts;
        var u = ((ts - t0) % period) / period;
        var v = spec.min + (spec.max - spec.min) * (opts.animate.pingpong ? (u < 0.5 ? 2 * u : 2 - 2 * u) : u);
        values[opts.animate.param] = v;
        if (spec._row) {
          spec._row._input.value = v;
          spec._row._out.textContent = v.toFixed(digitsOf(spec));
        }
        render();
        raf = requestAnimationFrame(frame);
      }
      btn.addEventListener('click', function () {
        running = !running;
        btn.textContent = running ? 'Pause' : 'Lancer l\'animation';
        btn.classList.toggle('is-on', running);
        if (running) { t0 = 0; raf = requestAnimationFrame(frame); }
        else if (raf) cancelAnimationFrame(raf);
      });
    }

    render();
    var ro = global.ResizeObserver ? new ResizeObserver(function () { render(); }) : null;
    if (ro && !opts.width) ro.observe(host);
    global.addEventListener('mviz:theme', render);
    return { render: render, values: values };
  }

  // ---------------------------------------------------------- diagramme libre
  /** mviz.draw(cible, {width, height, caption, draw(ctx, w, h)}) : canvas brut */
  function draw(target, opts) {
    var host = resolve(target);
    host.classList.add('mviz');
    host.innerHTML = '';
    var stage = el('div', 'mviz-stage', host);
    var canvas = el('canvas', null, stage);
    var ctx = canvas.getContext('2d');
    function render() {
      var w = opts.width || Math.max(280, host.clientWidth || 640);
      var h = opts.height || Math.round(w * (opts.ratio || 0.5));
      var dpr = global.devicePixelRatio || 1;
      canvas.width = w * dpr; canvas.height = h * dpr;
      canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      opts.draw(ctx, w, h, pal());
    }
    if (opts.caption) el('figcaption', 'mviz-caption', host).innerHTML = opts.caption;
    render();
    global.addEventListener('mviz:theme', render);
    return { render: render };
  }

  global.mviz = { plot: plot, draw: draw, palette: pal, color: color };
})(window);
