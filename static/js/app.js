(function () {
  "use strict";

  /* ---------- Google-style live suggestions ---------- */
  var input = document.getElementById("search-input");
  var box = document.getElementById("suggestions");
  if (input && box) {
    var timer = null, items = [], active = -1;

    function render(results) {
      box.innerHTML = "";
      items = results;
      active = -1;
      if (!results.length) { box.hidden = true; return; }
      results.forEach(function (r) {
        var li = document.createElement("li");
        var a = document.createElement("a");
        a.href = r.url;
        var av = r.avatar ? document.createElement("img") : document.createElement("span");
        av.className = "avatar" + (r.avatar ? "" : " avatar-initials");
        if (r.avatar) { av.src = r.avatar; av.alt = ""; } else { av.textContent = r.initials; }
        var txt = document.createElement("div");
        var strong = document.createElement("strong"); strong.textContent = r.name;
        var small = document.createElement("div"); small.className = "muted small";
        small.textContent = r.employee_id + (r.position ? " · " + r.position : "");
        txt.appendChild(strong); txt.appendChild(small);
        a.appendChild(av); a.appendChild(txt); li.appendChild(a); box.appendChild(li);
      });
      box.hidden = false;
    }

    input.addEventListener("input", function () {
      clearTimeout(timer);
      var q = input.value.trim();
      if (!q) { box.hidden = true; return; }
      timer = setTimeout(function () {
        fetch(input.dataset.suggestUrl + "?q=" + encodeURIComponent(q), { credentials: "same-origin" })
          .then(function (r) { return r.json(); })
          .then(function (d) { if (input.value.trim() === q) render(d.results); })
          .catch(function () { box.hidden = true; });
      }, 150);
    });

    input.addEventListener("keydown", function (e) {
      var lis = box.querySelectorAll("li");
      if (box.hidden || !lis.length) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + lis.length) % lis.length;
        lis.forEach(function (li, i) { li.classList.toggle("active", i === active); });
      } else if (e.key === "Enter" && active >= 0) {
        e.preventDefault();
        window.location.href = items[active].url;
      } else if (e.key === "Escape") { box.hidden = true; }
    });
    document.addEventListener("click", function (e) { if (!box.contains(e.target) && e.target !== input) box.hidden = true; });
  }

  /* ---------- Leave form: one row (from / to time) per working day ---------- */
  var form = document.getElementById("leave-form");
  if (form) {
    var typeSel = form.querySelector("[name=leave_type]");
    var startIn = form.querySelector("[name=start_date]");
    var endIn = form.querySelector("[name=end_date]");
    var body = document.getElementById("day-rows");
    var emptyNote = document.getElementById("day-empty");
    var totalNote = document.getElementById("day-total");
    var limitValue = document.getElementById("limit-value");
    var holidays = new Set((form.dataset.holidays || "").split(",").filter(Boolean));
    var weekdays = (form.dataset.weekdays || "0,1,2,3,4").split(",").map(Number);
    var hourlyTypes = (form.dataset.hourlyTypes || "").split(",").filter(Boolean);
    var defaultStart = form.dataset.defaultStart || "09:00";
    var defaultLimit = parseFloat(form.dataset.defaultLimit) || 8;
    var limits = {};
    (form.dataset.typeLimits || "").split(",").forEach(function (p) { var kv = p.split(":"); if (kv.length === 2) limits[kv[0]] = parseFloat(kv[1]); });
    var MAX_ROWS = 62;

    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    var limit = function () { return limits[typeSel.value] || defaultLimit; };
    var partialOk = function () { return hourlyTypes.indexOf(typeSel.value) !== -1; };
    function toMin(v) { var m = /^(\d{1,2}):(\d{2})/.exec(v || ""); return m ? (+m[1]) * 60 + (+m[2]) : null; }
    function fromMin(n) { n = Math.max(0, Math.min(Math.round(n), 23 * 60 + 59)); return pad(Math.floor(n / 60)) + ":" + pad(n % 60); }
    function parseISO(s) { var p = s.split("-"); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])); }
    function iso(d) { return d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate()); }
    function fmtDay(d) { return d.toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }); }
    function fullDayEnd(start) { return fromMin((toMin(start) || 0) + limit() * 60); }

    function cell(tr, name) { return tr.querySelector("[name=" + name + "]"); }
    function makeRow(dateIso, vals) {
      var tr = document.createElement("tr");
      tr.dataset.date = dateIso;
      var td0 = document.createElement("td");
      td0.appendChild(document.createTextNode(fmtDay(parseISO(dateIso))));
      var hid = document.createElement("input"); hid.type = "hidden"; hid.name = "day_date"; hid.value = dateIso;
      td0.appendChild(hid);
      var td1 = document.createElement("td"), td2 = document.createElement("td"), td3 = document.createElement("td");
      td3.className = "num";
      [["day_start", td1, vals.start], ["day_end", td2, vals.end]].forEach(function (x) {
        var i = document.createElement("input"); i.type = "time"; i.name = x[0]; i.step = 900; i.required = true; i.value = x[2];
        i.addEventListener("input", recalc); x[1].appendChild(i);
      });
      var span = document.createElement("span"); span.className = "day-hours"; td3.appendChild(span);
      [td0, td1, td2, td3].forEach(function (td) { tr.appendChild(td); });
      return tr;
    }

    function rebuild() {
      var old = {};
      body.querySelectorAll("tr").forEach(function (tr) { old[tr.dataset.date] = { start: cell(tr, "day_start").value, end: cell(tr, "day_end").value }; });
      body.textContent = "";
      var s = startIn.value, e = endIn.value || s;
      if (s && e) {
        var a = parseISO(s), b = parseISO(e), n = 0;
        if (b >= a && (b - a) / 864e5 < MAX_ROWS) {
          for (var d = new Date(a); d <= b && n < MAX_ROWS; d = new Date(d.getTime() + 864e5)) {
            var dow = (d.getUTCDay() + 6) % 7;                    // Monday = 0, like Django
            if (weekdays.indexOf(dow) === -1 || holidays.has(iso(d))) continue;
            var key = iso(d), vals = old[key] || { start: defaultStart, end: fullDayEnd(defaultStart) };
            body.appendChild(makeRow(key, vals)); n++;
          }
        }
      }
      applyType(false);
      recalc();
    }

    function applyType(force) {
      if (limitValue) limitValue.textContent = limit();
      var fixed = !partialOk();
      body.querySelectorAll("tr").forEach(function (tr) {
        var st = cell(tr, "day_start"), en = cell(tr, "day_end");
        if (fixed && force) { st.value = st.value || defaultStart; en.value = fullDayEnd(st.value); }
        else if (force) { var m = toMin(en.value) - toMin(st.value); if (!(m > 0) || m > limit() * 60) en.value = fullDayEnd(st.value); }
        en.readOnly = fixed;            // full-day leave types: only the start time can move
      });
      recalc();
    }

    function recalc() {
      var total = 0, rows = body.querySelectorAll("tr");
      var fixed = !partialOk();
      rows.forEach(function (tr) {
        var st = cell(tr, "day_start"), en = cell(tr, "day_end"), out = tr.querySelector(".day-hours");
        if (fixed && st.value) en.value = fullDayEnd(st.value);
        var h = (toMin(en.value) - toMin(st.value)) / 60;
        if (!(h > 0)) { out.textContent = "\u2013"; out.classList.add("over"); return; }
        out.textContent = (Math.round(h * 100) / 100) + " h";
        out.classList.toggle("over", h > limit() + 1e-9);
        total += h;
      });
      emptyNote.hidden = rows.length > 0;
      totalNote.hidden = rows.length === 0;
      totalNote.textContent = rows.length + " day" + (rows.length === 1 ? "" : "s") + " \u00B7 " + (Math.round(total * 100) / 100) + " h in total"
        + (fixed ? " \u00B7 this leave type is taken in full days" : "");
    }

    typeSel.addEventListener("change", function () { applyType(true); });
    startIn.addEventListener("change", function () { if (!endIn.value || endIn.value < startIn.value) endIn.value = ""; rebuild(); });
    endIn.addEventListener("change", rebuild);
    document.getElementById("fill-full").addEventListener("click", function () {
      body.querySelectorAll("tr").forEach(function (tr) { cell(tr, "day_start").value = defaultStart; cell(tr, "day_end").value = fullDayEnd(defaultStart); });
      recalc();
    });
    document.getElementById("copy-first").addEventListener("click", function () {
      var rows = body.querySelectorAll("tr"); if (!rows.length) return;
      var st = cell(rows[0], "day_start").value, en = cell(rows[0], "day_end").value;
      rows.forEach(function (tr) { cell(tr, "day_start").value = st; cell(tr, "day_end").value = en; });
      recalc();
    });
    rebuild();      // also re-renders rows that came back from the server after a validation error
  }

  /* ---------- people picker (broadcast + newsletter publishers) ---------- */
  document.querySelectorAll("[data-filter-list]").forEach(function (input) {
    var list = document.getElementById(input.dataset.filterList);
    if (!list) return;
    input.addEventListener("input", function () {
      var q = input.value.trim().toLowerCase();
      list.querySelectorAll(".pick-item").forEach(function (it) { it.hidden = q && it.textContent.toLowerCase().indexOf(q) === -1; });
    });
  });
  document.querySelectorAll("[data-pick]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var list = document.getElementById(btn.dataset.target); if (!list) return;
      list.querySelectorAll(".pick-item").forEach(function (it) {
        var box = it.querySelector("input[type=checkbox]"); if (box && !it.hidden) box.checked = btn.dataset.pick === "all";
      });
    });
  });
  var audience = document.querySelectorAll("input[name=audience]");
  var picker = document.getElementById("people-picker");
  if (audience.length && picker) {
    var syncAudience = function () {
      var v = (document.querySelector("input[name=audience]:checked") || {}).value;
      picker.hidden = v !== "selected";
    };
    audience.forEach(function (r) { r.addEventListener("change", syncAudience); });
    syncAudience();
  }

  /* ---------- newsletter image lightbox ---------- */
  document.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest("a.gallery-link");
    if (!link) return;
    e.preventDefault();
    var box = document.createElement("div"); box.className = "lightbox"; box.setAttribute("role", "dialog");
    var img = document.createElement("img"); img.src = link.href; img.alt = link.dataset.alt || "";
    box.appendChild(img);
    function close() { box.remove(); document.removeEventListener("keydown", onKey); }
    function onKey(ev) { if (ev.key === "Escape") close(); }
    box.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    document.body.appendChild(box);
  });

  /* ---------- confirm destructive forms (no inline handlers: CSP) ---------- */
  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (f.classList && f.classList.contains("js-confirm") && !window.confirm(f.dataset.confirm || "Are you sure?")) e.preventDefault();
  });

  /* ---------- dropdown menus: close on outside click / Escape ---------- */
  var menus = document.querySelectorAll("details.menu");
  document.addEventListener("click", function (e) { menus.forEach(function (m) { if (!m.contains(e.target)) m.removeAttribute("open"); }); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") menus.forEach(function (m) { m.removeAttribute("open"); }); });
})();

/* ---------- picture uploads: client-side pre-check + local previews ----------
   Only .jpg/.jpeg/.png up to data-max-mb are accepted here; the server repeats and enforces every check
   (real image format, size, dimensions) and re-encodes the file, so this is purely a convenience. */
(function () {
  "use strict";
  var OK_EXT = /\.(jpe?g|png)$/i, OK_TYPE = /^image\/(jpeg|png)$/;

  function fmtSize(b) { return b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB"; }

  // Draw a downscaled copy on a canvas -> data: URL (CSP allows data: but not blob:). Also proves the file decodes.
  function thumb(file, done) {
    function fallback() {
      var r = new FileReader();
      r.onload = function () { done(null, r.result); };
      r.onerror = function () { done(new Error("unreadable")); };
      r.readAsDataURL(file);
    }
    if (!window.createImageBitmap) { fallback(); return; }
    createImageBitmap(file).then(function (bmp) {
      var k = Math.min(1, 900 / Math.max(bmp.width, bmp.height));
      var c = document.createElement("canvas");
      c.width = Math.max(1, Math.round(bmp.width * k)); c.height = Math.max(1, Math.round(bmp.height * k));
      c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
      if (bmp.close) bmp.close();
      done(null, c.toDataURL(/png$/.test(file.type) ? "image/png" : "image/jpeg", 0.88));
    }).catch(function () { done(new Error("unreadable")); });
  }

  function problem(file, maxBytes) {
    if (!OK_EXT.test(file.name) || (file.type && !OK_TYPE.test(file.type))) return "“" + file.name + "” is not allowed. Use a .jpg, .jpeg or .png picture.";
    if (file.size > maxBytes) return "“" + file.name + "” is " + fmtSize(file.size) + " - the limit is " + fmtSize(maxBytes) + ".";
    if (file.size === 0) return "“" + file.name + "” is empty.";
    return "";
  }

  document.querySelectorAll("input[type=file][data-image-upload]").forEach(function (input) {
    if (input.multiple) return;                  // multi-picture dropzones are handled below
    var wrap = input.closest("[data-upload]") || input.parentNode;
    var errBox = wrap.querySelector(".js-upload-error"), meta = wrap.querySelector(".js-upload-meta");
    var undo = wrap.querySelector(".js-upload-reset"), grid = wrap.querySelector(".js-preview-grid");
    var remove = wrap.querySelector("input[data-remove-for]");
    var preview = document.getElementById("preview-" + input.name);
    var fallbackEl = preview && preview.dataset.fallback ? document.getElementById(preview.dataset.fallback) : null;
    var original = preview ? preview.getAttribute("src") : null;
    var maxBytes = (parseFloat(input.dataset.maxMb) || 20) * 1048576;
    var maxFiles = parseInt(input.dataset.maxFiles, 10) || (input.multiple ? 6 : 1);

    function showError(msg) { if (!errBox) return; errBox.textContent = msg; errBox.hidden = !msg; }
    function showOriginal() {
      if (!preview) return;
      var gone = remove && remove.checked;
      if (original && !gone) { preview.src = original; preview.hidden = false; if (fallbackEl) fallbackEl.hidden = true; }
      else { preview.hidden = true; preview.removeAttribute("src"); if (fallbackEl) fallbackEl.hidden = false; }
    }
    function reset() {
      input.value = ""; showError(""); if (meta) meta.hidden = true; if (undo) undo.hidden = true;
      if (grid) grid.textContent = "";
      showOriginal();
    }

    input.addEventListener("change", function () {
      var files = Array.prototype.slice.call(input.files || []);
      showError(""); if (grid) grid.textContent = "";
      if (!files.length) { reset(); return; }
      var errors = [], good = [];
      files.forEach(function (f) { var m = problem(f, maxBytes); if (m) errors.push(m); else good.push(f); });
      if (good.length > maxFiles) { errors.push("You can add at most " + maxFiles + " picture" + (maxFiles === 1 ? "" : "s") + " at a time."); good = good.slice(0, maxFiles); }
      if (errors.length) {
        showError(errors.join(" "));
        try {                                   // keep the acceptable files, drop the rest
          var dt = new DataTransfer(); good.forEach(function (f) { dt.items.add(f); }); input.files = dt.files;
        } catch (e) { input.value = ""; good = []; }
      }
      if (!good.length) { if (meta) meta.hidden = true; if (undo) undo.hidden = true; showOriginal(); return; }
      if (meta) { meta.textContent = good.map(function (f) { return f.name + " (" + fmtSize(f.size) + ")"; }).join(", "); meta.hidden = false; }
      if (undo) undo.hidden = false;
      if (remove) remove.checked = false;      // a new file replaces the old one; "remove" no longer applies
      good.forEach(function (f) {
        thumb(f, function (err, url) {
          if (err) { showError("“" + f.name + "” could not be read as a picture."); input.value = ""; if (grid) grid.textContent = ""; if (undo) undo.hidden = true; showOriginal(); return; }
          if (grid) {
            var fig = document.createElement("figure"), im = document.createElement("img"), cap = document.createElement("figcaption");
            im.src = url; im.alt = "Preview of " + f.name; cap.textContent = f.name; fig.appendChild(im); fig.appendChild(cap); grid.appendChild(fig);
          } else if (preview) {
            preview.src = url; preview.hidden = false; if (fallbackEl) fallbackEl.hidden = true;
          }
        });
      });
    });
    if (undo) undo.addEventListener("click", reset);
    if (remove) remove.addEventListener("change", function () { if (remove.checked) { input.value = ""; showError(""); if (meta) meta.hidden = true; if (undo) undo.hidden = true; } showOriginal(); });
  });

  /* ---------- multi-picture dropzone (newsletter posts): add in several rounds, remove one by one ---------- */
  document.querySelectorAll("input[type=file][data-image-upload][multiple]").forEach(function (input) {
    var wrap = input.closest("[data-upload]") || input.parentNode;
    var zone = wrap.querySelector(".dropzone"), errBox = wrap.querySelector(".js-upload-error");
    var grid = wrap.querySelector(".js-preview-grid"), counter = wrap.querySelector(".js-upload-count");
    var form = input.form;
    var maxBytes = (parseFloat(input.dataset.maxMb) || 20) * 1048576;
    var maxFiles = parseInt(input.dataset.maxFiles, 10) || 6;
    var selected = [], cache = {};

    function key(f) { return f.name + "|" + f.size + "|" + f.lastModified; }
    function kept() {                           // pictures already on the post that are not ticked for removal
      var n = 0;
      if (form) form.querySelectorAll("input[name=remove_images]").forEach(function (c) { if (!c.checked) n++; });
      return n;
    }
    function room() { return Math.max(0, maxFiles - kept()); }
    function showError(m) { if (errBox) { errBox.textContent = m; errBox.hidden = !m; } }
    function sync() {                           // keep the real <input> in step with our list, so the form submits it
      try { var dt = new DataTransfer(); selected.forEach(function (f) { dt.items.add(f); }); input.files = dt.files; }
      catch (e) { /* very old browsers: the native selection is submitted as is */ }
    }
    function drop(f) { selected = selected.filter(function (x) { return x !== f; }); sync(); render(); }

    function render() {
      grid.textContent = "";
      selected.forEach(function (f) {
        var fig = document.createElement("figure"), im = document.createElement("img"), cap = document.createElement("figcaption");
        var rm = document.createElement("button");
        rm.type = "button"; rm.className = "dz-remove"; rm.textContent = "\u00d7"; rm.setAttribute("aria-label", "Remove " + f.name);
        rm.addEventListener("click", function () { drop(f); showError(""); });
        im.alt = "Preview of " + f.name; cap.textContent = f.name + " \u00B7 " + fmtSize(f.size);
        var k = key(f);
        if (cache[k]) im.src = cache[k];
        else thumb(f, function (err, url) {
          if (err) { showError("\u201C" + f.name + "\u201D could not be read as a picture."); drop(f); return; }
          cache[k] = url; im.src = url;
        });
        fig.appendChild(im); fig.appendChild(cap); fig.appendChild(rm); grid.appendChild(fig);
      });
      if (zone) zone.classList.toggle("has-files", selected.length > 0);
      if (counter) {
        var left = Math.max(0, room() - selected.length);
        counter.textContent = selected.length ? selected.length + " selected \u00B7 " + left + " more allowed" : "Up to " + room() + " picture" + (room() === 1 ? "" : "s") + " can be added.";
      }
    }

    function add(list) {
      var errs = [];
      Array.prototype.slice.call(list).forEach(function (f) {
        if (selected.some(function (x) { return key(x) === key(f); })) return;        // same file twice
        var m = problem(f, maxBytes);
        if (m) { errs.push(m); return; }
        if (selected.length >= room()) { var lim = "A post can have at most " + maxFiles + " pictures."; if (errs.indexOf(lim) === -1) errs.push(lim); return; }
        selected.push(f);
      });
      sync(); render(); showError(errs.join(" "));
    }

    input.addEventListener("change", function () { add(input.files); });
    if (form) form.querySelectorAll("input[name=remove_images]").forEach(function (c) { c.addEventListener("change", function () { render(); showError(selected.length > room() ? "Too many pictures - remove some of the new ones." : ""); }); });
    if (zone) {
      ["dragenter", "dragover"].forEach(function (ev) { zone.addEventListener(ev, function () { zone.classList.add("is-over"); }); });
      ["dragleave", "drop", "dragend"].forEach(function (ev) { zone.addEventListener(ev, function () { zone.classList.remove("is-over"); }); });
    }
    render();
  });

  /* ---------- group form: live preview ---------- */
  var gName = document.getElementById("id_name"), gDesc = document.getElementById("id_description"), gMgr = document.getElementById("id_manager");
  if (document.getElementById("group-form") && gName) {
    var pvName = document.getElementById("gp-name"), pvDesc = document.getElementById("gp-desc"), pvMgr = document.getElementById("gp-manager");
    var gCount = document.getElementById("gf-desc-count");
    var syncGroup = function () {
      pvName.textContent = gName.value.trim() || "Group name";
      pvDesc.textContent = gDesc ? gDesc.value : "";
      if (gCount && gDesc) gCount.textContent = gDesc.value.length;
      if (gMgr) pvMgr.textContent = gMgr.value ? gMgr.options[gMgr.selectedIndex].text.replace(/\s*\(.*\)\s*$/, "") : "none assigned";
    };
    [gName, gDesc, gMgr].forEach(function (el) { if (el) { el.addEventListener("input", syncGroup); el.addEventListener("change", syncGroup); } });
    syncGroup();
  }

  /* live text preview on the Edit profile page */
  [["id_contact_info", "pv-contact"], ["id_description", "pv-desc"]].forEach(function (pair) {
    var src = document.getElementById(pair[0]), dst = document.getElementById(pair[1]);
    if (!src || !dst) return;
    function sync() { dst.textContent = src.value; }          // textContent: never interpreted as HTML
    src.addEventListener("input", sync); sync();
  });
  var desc = document.getElementById("id_description"), count = document.getElementById("desc-count");
  if (desc && count) { var upd = function () { count.textContent = desc.value.length; }; desc.addEventListener("input", upd); upd(); }
})();
