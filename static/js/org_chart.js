/* Org chart: endless pan / zoom canvas (port of the original Hierarchical_Vision canvas.js).
   All DOM is built with createElement/textContent - employee data is never injected as HTML. */
(function () {
  'use strict';
  var canvas = document.getElementById('org-canvas');
  if (!canvas) return;

  var content = document.getElementById('canvas-content');
  var zoomLabel = document.getElementById('zoom-level');
  var searchInput = document.getElementById('chart-search-input');
  var overlay = document.getElementById('search-overlay');
  var resultsGrid = document.getElementById('results-grid');
  var lineageBox = document.getElementById('lineage-container');
  var lineageChain = document.getElementById('lineage-chain');
  var crumbs = document.getElementById('breadcrumbs');
  var toast = document.getElementById('chart-toast');

  var byId = new Map();        // id -> user
  var kids = new Map();        // id -> [user]
  var records = new Map();     // id -> {user, node, card, toggle, container, rendered}
  var roots = [];
  var MIN_K = 0.15, MAX_K = 2.5;
  var view = { x: 0, y: 0, k: 1 };
  var animTimer = null;

  /* ------------------------------------------------------------------ view / camera */
  function clamp(k) { return Math.min(MAX_K, Math.max(MIN_K, k)); }
  function apply() {
    content.style.transform = 'translate(' + view.x + 'px,' + view.y + 'px) scale(' + view.k + ')';
    zoomLabel.textContent = Math.round(view.k * 100) + '%';
  }
  function animateTo(x, y, k) {
    content.classList.add('animating');
    view.x = x; view.y = y; view.k = k; apply();
    clearTimeout(animTimer);
    animTimer = setTimeout(function () { content.classList.remove('animating'); }, 500);
  }
  function zoomAt(factor, cx, cy) {
    var k = clamp(view.k * factor), r = k / view.k;
    view.x = cx - (cx - view.x) * r;
    view.y = cy - (cy - view.y) * r;
    view.k = k;
    apply();
  }
  function zoomCenter(factor) {
    content.classList.add('animating');
    zoomAt(factor, canvas.clientWidth / 2, canvas.clientHeight / 2);
    clearTimeout(animTimer);
    animTimer = setTimeout(function () { content.classList.remove('animating'); }, 500);
  }
  function fit(animate) {
    var w = content.offsetWidth, h = content.offsetHeight, vw = canvas.clientWidth, vh = canvas.clientHeight;
    if (!w || !h) return;
    var k = clamp(Math.min(vw / w, vh / h, 1));
    var x = (vw - w * k) / 2, y = Math.max(0, (vh - h * k) / 4);
    if (animate) animateTo(x, y, k); else { view.x = x; view.y = y; view.k = k; apply(); }
  }
  function worldCenter(el) {                       // centre of el in unscaled canvas coordinates
    var x = 0, y = 0, n = el;
    while (n && n !== content) { x += n.offsetLeft; y += n.offsetTop; n = n.offsetParent; }
    return { x: x + el.offsetWidth / 2, y: y + el.offsetHeight / 2 };
  }
  function centerOn(el, k) {
    var c = worldCenter(el), nk = clamp(k || view.k);
    animateTo(canvas.clientWidth / 2 - c.x * nk, canvas.clientHeight / 2 - c.y * nk, nk);
  }

  /* ------------------------------------------------------------------ pointer: drag + pinch */
  var pointers = new Map(), drag = null, moved = false, lastPinch = null;
  function interactive(t) { return t.closest('.chart-ui, button, a, input'); }
  canvas.addEventListener('pointerdown', function (e) {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    if (interactive(e.target)) return;
    content.classList.remove('animating');
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
    if (pointers.size === 1) {
      drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
      moved = false;
    } else if (pointers.size === 2) {
      drag = null; lastPinch = null;
    }
  });
  canvas.addEventListener('pointermove', function (e) {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2) {
      var p = Array.from(pointers.values());
      var dist = Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y);
      var mid = { x: (p[0].x + p[1].x) / 2, y: (p[0].y + p[1].y) / 2 };
      var r = canvas.getBoundingClientRect();
      if (lastPinch) {
        view.x += mid.x - lastPinch.mid.x; view.y += mid.y - lastPinch.mid.y;
        zoomAt(dist / lastPinch.dist, mid.x - r.left, mid.y - r.top);
      }
      lastPinch = { dist: dist, mid: mid }; moved = true;
    } else if (drag) {
      var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!moved && Math.abs(dx) + Math.abs(dy) > 4) { moved = true; canvas.classList.add('dragging'); }
      if (moved) { view.x = drag.vx + dx; view.y = drag.vy + dy; apply(); }
    }
  });
  function endPointer(e) {
    pointers.delete(e.pointerId);
    lastPinch = null;
    if (pointers.size === 1) {
      var rest = Array.from(pointers.values())[0];
      drag = { x: rest.x, y: rest.y, vx: view.x, vy: view.y };
    } else if (pointers.size === 0) {
      drag = null; canvas.classList.remove('dragging');
    }
  }
  canvas.addEventListener('pointerup', endPointer);
  canvas.addEventListener('pointercancel', endPointer);
  canvas.addEventListener('click', function (e) { if (moved) { e.stopPropagation(); e.preventDefault(); moved = false; } }, true);

  canvas.addEventListener('wheel', function (e) {
    if (e.target.closest('.search-results-overlay')) return;     // let the results list scroll
    e.preventDefault();
    content.classList.remove('animating');
    var d = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
    if (e.shiftKey) { view.x -= d; apply(); return; }
    var r = canvas.getBoundingClientRect();
    zoomAt(Math.exp(-d * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });

  canvas.addEventListener('keydown', function (e) {
    if (e.target.tagName === 'INPUT') return;
    var step = 60;
    if (e.key === '+' || e.key === '=') zoomCenter(1.2);
    else if (e.key === '-' || e.key === '_') zoomCenter(1 / 1.2);
    else if (e.key === '0') fit(true);
    else if (e.key === 'ArrowLeft') { view.x += step; apply(); }
    else if (e.key === 'ArrowRight') { view.x -= step; apply(); }
    else if (e.key === 'ArrowUp') { view.y += step; apply(); }
    else if (e.key === 'ArrowDown') { view.y -= step; apply(); }
    else return;
    e.preventDefault();
  });

  document.getElementById('zoom-in').addEventListener('click', function () { zoomCenter(1.25); });
  document.getElementById('zoom-out').addEventListener('click', function () { zoomCenter(1 / 1.25); });
  document.getElementById('fit-view').addEventListener('click', function () { fit(true); });
  document.getElementById('expand-all').addEventListener('click', function () {
    var n = 0;
    records.forEach(function () { n++; });
    if (byId.size > 400 && !window.confirm('Expanding ' + byId.size + ' people may be slow. Continue?')) return;
    var stack = roots.slice();
    while (stack.length) {
      var u = stack.pop(), rec = records.get(u.id);
      if (rec && rec.toggle) { setExpanded(rec, true); (kids.get(u.id) || []).forEach(function (c) { stack.push(c); }); }
    }
    hideCrumbs();
    setTimeout(function () { fit(true); }, 50);
  });
  document.getElementById('collapse-all').addEventListener('click', function () {
    records.forEach(function (rec) { if (rec.toggle) setExpanded(rec, false); });
    hideCrumbs();
    setTimeout(function () { fit(true); }, 50);
  });

  /* ------------------------------------------------------------------ building cards */
  var SVG_CHEVRON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"></path></svg>';
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function avatar(u) {
    var box = el('div', 'profile-pic' + (u.image_url ? '' : ' initials'));
    if (u.image_url) {
      var img = document.createElement('img');
      img.src = u.image_url; img.alt = u.name; img.loading = 'lazy'; img.draggable = false;
      box.appendChild(img);
    } else { box.textContent = u.initials; }
    return box;
  }
  function linkButton(label, href, primary) {
    var a = el('a', 'btn' + (primary ? ' btn-primary' : ''), label);
    a.href = href;
    return a;
  }
  function memberCard(u, opts) {
    opts = opts || {};
    var card = el('div', 'member-card');
    card.dataset.id = u.id;
    card.appendChild(avatar(u));
    var name = el('div', 'member-name');
    if (opts.plainName) { name.textContent = u.name; }
    else { var a = el('a', null, u.name); a.href = u.profile_url; name.appendChild(a); }
    card.appendChild(name);
    card.appendChild(el('div', 'member-id', u.employee_id));
    if (u.position) card.appendChild(el('div', 'member-position', u.position));
    if (u.email) card.appendChild(el('div', 'member-info', u.email));
    if (u.contact) card.appendChild(el('div', 'member-info', u.contact));
    var n = (kids.get(u.id) || []).length;
    if (n > 0) card.appendChild(el('div', 'report-count', String(n)));
    if (!opts.plainName && canvas.dataset.isAdmin === '1' && u.edit_url) {
      var actions = el('div', 'card-actions');
      actions.appendChild(linkButton('Add', u.add_url, true));
      actions.appendChild(linkButton('Edit', u.edit_url, false));
      card.appendChild(actions);
    }
    return card;
  }
  function createNode(u, branch) {
    var node = el('div', 'tree-node');
    if (branch !== null) { node.classList.add('branch-' + (branch % 6)); node.dataset.branch = branch; }
    var card = memberCard(u);
    node.appendChild(card);
    var container = el('div', 'subordinates-container');
    node.appendChild(container);
    var rec = { user: u, node: node, card: card, toggle: null, container: container, rendered: false, branch: branch };
    if ((kids.get(u.id) || []).length) {
      var t = el('button', 'expand-toggle');
      t.type = 'button';
      t.innerHTML = SVG_CHEVRON;                 // static constant markup only
      t.setAttribute('aria-expanded', 'false');
      t.setAttribute('aria-label', 'Show direct reports of ' + u.name);
      t.addEventListener('click', function (e) { e.stopPropagation(); toggle(rec); });
      card.appendChild(t);
      rec.toggle = t;
    }
    records.set(u.id, rec);
    return node;
  }
  function setExpanded(rec, open) {
    if (!rec.toggle) return;
    if (open && !rec.rendered) {
      (kids.get(rec.user.id) || []).forEach(function (c, i) {
        rec.container.appendChild(createNode(c, rec.branch === null ? i : rec.branch));
      });
      rec.rendered = true;
    }
    rec.node.classList.toggle('expanded', open);
    rec.toggle.classList.toggle('open', open);
    rec.toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  function toggle(rec) {
    // keep the clicked card fixed on screen while the layout grows / shrinks around it
    var before = worldCenter(rec.card);
    content.classList.remove('animating');
    setExpanded(rec, !rec.node.classList.contains('expanded'));
    var after = worldCenter(rec.card);
    view.x += (before.x - after.x) * view.k;
    view.y += (before.y - after.y) * view.k;
    apply();
  }

  /* ------------------------------------------------------------------ lineage, search, reveal */
  function chainTo(id) {                           // root ... person
    var out = [], seen = new Set(), u = byId.get(id);
    while (u && !seen.has(u.id)) { out.unshift(u); seen.add(u.id); u = byId.get(u.manager_id); }
    return out;
  }
  function hideCrumbs() { crumbs.hidden = true; crumbs.textContent = ''; }
  function showCrumbs(chain) {
    crumbs.textContent = '';
    chain.forEach(function (u, i) {
      if (i) crumbs.appendChild(el('span', null, '\u203A'));
      var item = el('span', 'breadcrumb-item', u.name);
      item.addEventListener('click', function () { focusUser(u.id, false); });
      crumbs.appendChild(item);
    });
    crumbs.hidden = false;
  }
  function focusUser(id, withCrumbs) {
    var chain = chainTo(id);
    chain.slice(0, -1).forEach(function (a) { var r = records.get(a.id); if (r) setExpanded(r, true); });
    var rec = records.get(id);
    if (!rec) return;
    document.querySelectorAll('.member-card.located').forEach(function (c) { c.classList.remove('located'); });
    rec.card.classList.add('located');
    setTimeout(function () { rec.card.classList.remove('located'); }, 3200);
    if (withCrumbs !== false) showCrumbs(chain);
    centerOn(rec.card, Math.max(view.k, 0.9));
  }
  function closeSearch() { overlay.hidden = true; }
  document.getElementById('close-search').addEventListener('click', function () { closeSearch(); searchInput.value = ''; });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !overlay.hidden) { closeSearch(); } });

  function matches(u, q) {
    var hay = (u.name + ' ' + u.employee_id).toLowerCase();
    return q.toLowerCase().split(/\s+/).every(function (t) { return hay.indexOf(t) !== -1; });
  }
  function runSearch() {
    var q = searchInput.value.trim();
    if (!q) { closeSearch(); return; }
    var found = [];
    byId.forEach(function (u) { if (matches(u, q)) found.push(u); });
    found.sort(function (a, b) { return a.name.localeCompare(b.name); });
    found = found.slice(0, 60);
    resultsGrid.textContent = '';
    lineageChain.textContent = '';
    if (!found.length) { resultsGrid.appendChild(el('p', 'empty-chart', 'No employees found for \u201C' + q + '\u201D.')); }
    found.forEach(function (u) {
      var c = memberCard(u, { plainName: true });
      c.addEventListener('click', function () { closeSearch(); searchInput.value = ''; focusUser(u.id, true); });
      resultsGrid.appendChild(c);
    });
    if (found.length === 1) {
      chainTo(found[0].id).forEach(function (u) {
        var item = el('div', 'lineage-item');
        item.appendChild(el('strong', null, u.name));
        item.appendChild(document.createTextNode(' (' + u.employee_id + ')'));
        item.addEventListener('click', function () { closeSearch(); searchInput.value = ''; focusUser(u.id, true); });
        lineageChain.appendChild(item);
      });
      lineageBox.hidden = false;
    } else { lineageBox.hidden = true; }
    overlay.hidden = false;
  }
  var searchTimer = null;
  searchInput.addEventListener('input', function () { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 200); });
  searchInput.addEventListener('keydown', function (e) { if (e.key === 'Enter') { clearTimeout(searchTimer); runSearch(); } });

  /* ------------------------------------------------------------------ boot */
  function showToast(msg) { toast.textContent = msg; toast.hidden = false; setTimeout(function () { toast.hidden = true; }, 4000); }

  function init(users) {
    users.forEach(function (u) { byId.set(u.id, u); });
    byId.forEach(function (u) {
      if (u.manager_id && byId.has(u.manager_id)) {
        if (!kids.has(u.manager_id)) kids.set(u.manager_id, []);
        kids.get(u.manager_id).push(u);
      } else { roots.push(u); }
    });
    var byName = function (a, b) { return a.name.localeCompare(b.name); };
    kids.forEach(function (list) { list.sort(byName); });
    roots.sort(byName);

    content.textContent = '';
    if (!roots.length) { content.appendChild(el('div', 'empty-chart', 'No people to show yet.')); return; }
    roots.forEach(function (r) { content.appendChild(createNode(r, null)); });
    if (roots.length === 1) { var rec = records.get(roots[0].id); if (rec) setExpanded(rec, true); }
    requestAnimationFrame(function () { fit(false); canvas.focus({ preventScroll: true }); });
  }

  fetch(canvas.dataset.dataUrl, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function (data) { init(data.users); })
    .catch(function (err) { content.textContent = ''; content.appendChild(el('div', 'empty-chart', 'Could not load the chart (' + err.message + ').')); showToast('Could not load the chart'); });
})();
