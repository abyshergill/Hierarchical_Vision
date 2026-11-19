/* Leave & OT dashboard charts - plain SVG / DOM, no libraries (the site's CSP only allows our own scripts).
   Data arrives as JSON in #dash-data; nothing from it is ever inserted as HTML. Colours come from CSS variables so
   light and dark mode work. */
(function () {
  'use strict';
  var node = document.getElementById('dash-data');
  if (!node) return;
  var data;
  try { data = JSON.parse(node.textContent); } catch (err) { return; }
  var NS = 'http://www.w3.org/2000/svg';

  function svg(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(n);
    return n;
  }
  function html(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

  /* ---------------------------------------------------------------- tooltip (one shared element) */
  var tip = html('div', 'chart-tip');
  tip.hidden = true;
  document.body.appendChild(tip);
  function showTip(lines, x, y) {
    tip.textContent = '';
    lines.forEach(function (l, i) {
      var row = html('div', i ? 'tip-row' : 'tip-title');
      if (l.color) { var sw = html('i', 'sw'); sw.style.background = l.color; row.appendChild(sw); }
      row.appendChild(document.createTextNode(l.text));
      tip.appendChild(row);
    });
    tip.hidden = false;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.min(Math.max(8, x + 14), window.innerWidth - w - 8);
    var top = y - h - 14 < 8 ? y + 18 : y - h - 14;
    tip.style.left = left + 'px'; tip.style.top = top + 'px';
  }
  function hideTip() { tip.hidden = true; }
  function css(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  /* ---------------------------------------------------------------- month chart: rounded bars, two per day */
  function barPath(x, y, w, h, r) {                // rounded top corners only; the bar sits on the baseline
    r = Math.min(r, w / 2, h);
    return 'M' + x + ',' + (y + h) + 'V' + (y + r) + 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y + 'H' + (x + w - r) +
           'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) + 'V' + (y + h) + 'Z';
  }
  function monthChart() {
    var box = document.getElementById('chart-month');
    if (!box || !data.month || !data.month.length) return;
    box.textContent = '';
    var W = Math.max(320, box.clientWidth), H = W < 520 ? 230 : 280;
    var m = { t: 12, r: 8, b: 40, l: 32 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b;
    var days = data.month, n = days.length, slot = iw / n;
    var top = Math.max(4, Math.max.apply(null, days.map(function (d) { return Math.max(d.leave, d.ot); })));
    var step = top <= 8 ? 1 : top <= 20 ? 2 : top <= 50 ? 5 : top <= 100 ? 10 : Math.pow(10, Math.floor(Math.log10(top)));
    top = Math.ceil(top / step) * step;
    function Y(v) { return m.t + ih - (ih * v) / top; }
    var root = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, 'class': 'chart-svg', 'aria-hidden': 'true' }, box);

    // soft gradients: full colour at the top of each bar fading a little towards the baseline
    var defs = svg('defs', {}, root);
    [['g-leave', 'stop-leave'], ['g-ot', 'stop-ot']].forEach(function (g) {
      var lg = svg('linearGradient', { id: g[0], x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
      svg('stop', { offset: '0%', 'class': g[1], 'stop-opacity': 1 }, lg);
      svg('stop', { offset: '100%', 'class': g[1], 'stop-opacity': 0.55 }, lg);
    });

    for (var v = 0; v <= top; v += step) {
      svg('line', { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), 'class': v ? 'ch-grid' : 'ch-axis' }, root);
      svg('text', { x: m.l - 8, y: Y(v) + 4, 'class': 'ch-tick', 'text-anchor': 'end' }, root).textContent = String(v);
    }
    var every = n > 28 && W < 700 ? 5 : n > 20 && W < 520 ? 4 : W < 700 ? 3 : 2;
    var hot = svg('rect', { y: m.t, height: ih, rx: 8, 'class': 'ch-hot', visibility: 'hidden' }, root);
    var gw = Math.max(6, slot * 0.74), bw = Math.max(3, gw / 2 - 1);
    days.forEach(function (d, i) {
      var cx = m.l + slot * i + slot / 2, sel = d.d === data.selected;
      if (sel) svg('rect', { x: m.l + slot * i + 1, y: m.t, width: slot - 2, height: ih, rx: 8, 'class': 'ch-selected-band' }, root);
      else if (d.weekend) svg('rect', { x: m.l + slot * i + 1, y: m.t, width: slot - 2, height: ih, rx: 8, 'class': 'ch-weekend' }, root);
      [['leave', 'g-leave', -bw - 1], ['ot', 'g-ot', 1]].forEach(function (b) {
        var val = d[b[0]];
        if (!val) return;
        var h = ih - (Y(val) - m.t);
        svg('path', { d: barPath(cx + b[2], Y(val), bw, h, Math.min(8, bw / 2)), fill: 'url(#' + b[1] + ')', 'class': 'ch-bar' }, root);
      });
      var selIdx = days.findIndex(function (x) { return x.d === data.selected; });
      if (sel || (i % every === 0 && Math.abs(i - selIdx) > 1)) {      // never crowd the selected day's label
        svg('text', { x: cx, y: H - m.b + 17, 'class': 'ch-tick' + (sel ? ' ch-tick-sel' : ''), 'text-anchor': 'middle' }, root).textContent = String(Number(d.d.slice(8)));
      }
    });
    svg('text', { x: m.l, y: H - 6, 'class': 'ch-tick' }, root).textContent = data.monthName;

    // hover: highlight the day, tooltip, click opens it
    var hit = svg('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent', style: 'cursor:pointer' }, root);
    function indexAt(e) {
      var r = root.getBoundingClientRect(), px = ((e.clientX - r.left) / r.width) * W;
      return Math.min(n - 1, Math.max(0, Math.floor((px - m.l) / slot)));
    }
    hit.addEventListener('pointermove', function (e) {
      var i = indexAt(e), d = days[i];
      hot.setAttribute('x', m.l + slot * i + 1); hot.setAttribute('width', slot - 2); hot.setAttribute('visibility', 'visible');
      var lines = [{ text: d.label + (d.holiday ? ' · ' + d.holiday : d.weekend ? ' · weekend' : '') },
        { text: plural(d.leave, 'person', 'people') + ' on leave', color: css('--c0', '#2a78d6') },
        { text: plural(d.ot, 'person', 'people') + ' on overtime', color: css('--c1', '#eb6834') }];
      if (data.headcount) lines.push({ text: (100 * d.leave / data.headcount).toFixed(1) + '% of the team out' });
      showTip(lines, e.clientX, e.clientY);
    });
    hit.addEventListener('pointerleave', function () { hot.setAttribute('visibility', 'hidden'); hideTip(); });
    hit.addEventListener('click', function (e) { location.href = data.navBase + days[indexAt(e)].d; });
  }

  /* ---------------------------------------------------------------- donut */
  var MAX_SLICES = 8;                              // eight validated colours; anything beyond folds into "Other"
  function donut(boxId, legendId, items, valueKey, unit) {
    var box = document.getElementById(boxId);
    if (!box || !items.length) return;
    box.textContent = '';
    var rows = items.slice(0, MAX_SLICES).map(function (it, i) { return { name: it.name, v: it[valueKey], slot: i, hours: valueKey === 'people' ? it.hours : 0, people: valueKey === 'people' ? 0 : it.people }; });
    var rest = items.slice(MAX_SLICES);
    if (rest.length) rows.push({ name: 'Other (' + rest.length + ')', v: rest.reduce(function (a, b) { return a + b[valueKey]; }, 0), slot: 'o',
      hours: valueKey === 'people' ? rest.reduce(function (a, b) { return a + (b.hours || 0); }, 0) : 0,
      people: valueKey === 'people' ? 0 : rest.reduce(function (a, b) { return a + (b.people || 0); }, 0) });
    var total = rows.reduce(function (a, r) { return a + r.v; }, 0);
    if (!total) return;
    var S = 190, R = 88, r = 62, cx = S / 2, cy = S / 2;
    var root = svg('svg', { viewBox: '0 0 ' + S + ' ' + S, width: S, height: S, 'class': 'chart-svg', 'aria-hidden': 'true' }, box);
    var a0 = -Math.PI / 2;
    function pt(rad, a) { return (cx + rad * Math.cos(a)).toFixed(2) + ' ' + (cy + rad * Math.sin(a)).toFixed(2); }
    rows.forEach(function (row) {
      var frac = row.v / total, a1 = a0 + frac * Math.PI * 2 - (rows.length > 1 ? 0.03 : 0);   // small gap between slices
      var big = a1 - a0 > Math.PI ? 1 : 0, d;
      if (rows.length === 1) {
        d = 'M ' + pt(R, a0) + ' A ' + R + ' ' + R + ' 0 1 1 ' + pt(R, a0 + Math.PI) + ' A ' + R + ' ' + R + ' 0 1 1 ' + pt(R, a0 + Math.PI * 2 - 0.001) +
            ' L ' + pt(r, a0 + Math.PI * 2 - 0.001) + ' A ' + r + ' ' + r + ' 0 1 0 ' + pt(r, a0 + Math.PI) + ' A ' + r + ' ' + r + ' 0 1 0 ' + pt(r, a0) + ' Z';
      } else {
        d = 'M ' + pt(R, a0) + ' A ' + R + ' ' + R + ' 0 ' + big + ' 1 ' + pt(R, a1) + ' L ' + pt(r, a1) + ' A ' + r + ' ' + r + ' 0 ' + big + ' 0 ' + pt(r, a0) + ' Z';
      }
      var path = svg('path', { d: d, 'class': 'ch-slice slot-' + row.slot }, root);
      path.addEventListener('pointermove', function (e) {
        var lines = [{ text: row.name }, { text: plural(Number(row.v.toFixed(2)), unit[0], unit[1]) + ' · ' + Math.round(100 * row.v / total) + '%', color: css('--c' + (row.slot === 'o' ? 'o' : row.slot), '#999') }];
        if (row.hours) lines.push({ text: row.hours + ' h' });
        if (row.people) lines.push({ text: plural(row.people, 'person', 'people') });
        showTip(lines, e.clientX, e.clientY);
      });
      var mid = a0 + frac * Math.PI;                    // pop the slice out a little on hover
      path.addEventListener('pointerenter', function () { path.style.transform = 'translate(' + (Math.cos(mid) * 5).toFixed(1) + 'px,' + (Math.sin(mid) * 5).toFixed(1) + 'px)'; });
      path.addEventListener('pointerleave', function () { path.style.transform = ''; hideTip(); });
      a0 += frac * Math.PI * 2;
    });
    var big = svg('text', { x: cx, y: cy + 6, 'class': 'ch-center', 'text-anchor': 'middle' }, root);
    big.textContent = String(Number(total.toFixed(1)));
    var small = svg('text', { x: cx, y: cy + 24, 'class': 'ch-center-sub', 'text-anchor': 'middle' }, root);
    small.textContent = unit[1];
    // legend: same colours, same rows as the donut
    var legend = document.getElementById(legendId);
    if (legend) {
      legend.textContent = '';
      rows.forEach(function (row) {
        var li = html('li');
        li.appendChild(html('i', 'sw slot-bg-' + row.slot));
        li.appendChild(html('span', 'lg-name', row.name));
        var val = html('span', 'lg-val', valueKey === 'people' ? String(row.v) : Number(row.v.toFixed(2)) + ' h');
        li.appendChild(val);
        legend.appendChild(li);
      });
    }
  }

  function drawAll() {
    monthChart();
    donut('chart-types', 'legend-types', data.leaveTypes || [], 'people', ['person', 'people']);
    donut('chart-leave-teams', 'legend-leave-teams', data.leaveTeams || [], 'people', ['person', 'people']);
    donut('chart-ot-teams', 'legend-ot-teams', data.otTeams || [], 'hours', ['hour', 'hours']);
  }
  drawAll();
  var lastW = 0, timer = null;
  window.addEventListener('resize', function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var box = document.getElementById('chart-month');
      if (box && box.clientWidth !== lastW) { lastW = box.clientWidth; monthChart(); }
    }, 150);
  });
})();
