// The item panel on the trip page (day-first plan, P2). Plain fetch, no library: a click on an item
// (a leg, stay, activity, meal or section row, or an Edit / Edit this day link) opens that item's own
// page in a side panel (a full-screen sheet on a phone), fetched with ?panel=1 so it comes without the
// site chrome (trips/_panel_base.html). Editors get the item's edit page; readers its read-only view
// (trips:item_panel). Forms and links inside the panel stay in the panel; after a save the panel
// reloads, shows "Saved" and stays open, and the day (and any other day that shows the item) is swapped
// for a fresh copy from trips:day_fragment. A deleted item closes the panel. Without JavaScript none of
// this runs and every link goes to the item's page as before.
(function () {
  var panel = document.getElementById("item-panel");
  if (!panel) return;
  var body = panel.querySelector("[data-panel-body]");
  var tabsNav = panel.querySelector("[data-panel-tabs]");
  var heading = panel.querySelector("[data-panel-heading]");
  var savedNote = panel.querySelector("[data-panel-saved]");
  var tripPath = panel.dataset.tripPath;
  var TABS = [["details", "Details"], ["booking", "Booking"], ["people", "People"], ["contacts", "Contacts"],
              ["comments", "Comments"]];
  var HEADERS = { "X-Requested-With": "fetch" };
  var state = { origin: null, current: null, anchor: "", dayId: "", opener: null, tab: null, deleted: false };

  function withPanel(href) {
    var url = new URL(href, location.href);
    url.searchParams.set("panel", "1");
    return url;
  }

  // The item's page in the panel, coming back to itself after a save (its own "next").
  function entryUrl(href) {
    var url = withPanel(href);
    url.searchParams.delete("next");
    url.searchParams.set("next", url.pathname + "?panel=1");
    return url.pathname + url.search;
  }

  function request(url, options) {
    return fetch(url, Object.assign({ headers: HEADERS, credentials: "same-origin" }, options || {}));
  }

  // Scripts in fetched HTML don't run by themselves: run the page's inline ones (the leg page's zone
  // fill) and any script file the trip page hasn't already loaded. JSON data blocks are left alone.
  function runScripts(root) {
    root.querySelectorAll("script").forEach(function (old) {
      var type = old.getAttribute("type");
      if (type && type !== "text/javascript" && type !== "module") return;
      var src = old.getAttribute("src");
      if (src && Array.prototype.some.call(document.querySelectorAll('script[src="' + src + '"]'),
                                           function (s) { return !root.contains(s); })) return;
      var copy = document.createElement("script");
      if (src) copy.src = src; else copy.textContent = old.textContent;
      old.replaceWith(copy);
    });
  }

  function buildTabs() {
    // A tab exists when something belongs to it alone: a form marked "details people" shows on both,
    // but only a travellers field (marked "people") makes a People tab.
    var present = {};
    body.querySelectorAll("[data-panel-tab]").forEach(function (el) {
      var tokens = el.dataset.panelTab.split(/\s+/);
      if (tokens.length === 1) present[tokens[0]] = true;
    });
    var tabs = TABS.filter(function (t) { return present[t[0]]; });
    tabsNav.innerHTML = "";
    if (tabs.length < 2) { tabsNav.hidden = true; show(null); return; }
    tabsNav.hidden = false;
    tabs.forEach(function (t) {
      var button = document.createElement("button");
      button.type = "button";
      button.textContent = t[1];
      button.dataset.tab = t[0];
      button.setAttribute("role", "tab");
      button.addEventListener("click", function () { show(t[0]); });
      tabsNav.appendChild(button);
    });
    show(present[state.tab] ? state.tab : tabs[0][0]);
  }

  function show(tab) {
    state.tab = tab;
    body.querySelectorAll("[data-panel-tab]").forEach(function (el) {
      el.hidden = tab !== null && el.dataset.panelTab.split(/\s+/).indexOf(tab) < 0;
    });
    tabsNav.querySelectorAll("button").forEach(function (b) {
      b.setAttribute("aria-selected", b.dataset.tab === tab ? "true" : "false");
    });
  }

  function render(html, url) {
    body.innerHTML = html;
    state.current = url;
    var page = body.querySelector("[data-panel-page]");
    heading.textContent = page ? page.dataset.panelTitle.split(" — ")[0] : "";
    body.querySelectorAll(".crumbs, [data-panel-hide]").forEach(function (el) { el.hidden = true; });
    runScripts(body);
    buildTabs();
  }

  function problem(status) {
    body.innerHTML = '<p class="callout-warning text-sm">That didn\'t open (' + status + "). " +
                     '<a class="link-quiet font-medium" href="' + state.current + '">Open it on its own page</a>.</p>';
  }

  function load(url) {
    return request(url).then(function (response) {
      if (response.status === 404) { state.deleted = true; close(); return; }
      if (!response.ok) { state.current = url.replace(/[?&]panel=1/, ""); problem(response.status); return; }
      return response.text().then(function (html) { render(html, url); });
    });
  }

  function flashSaved() {
    savedNote.hidden = false;
    clearTimeout(flashSaved.timer);
    flashSaved.timer = setTimeout(function () { savedNote.hidden = true; }, 2500);
  }

  // Swap in fresh copies of the item's day and of any other day that shows it (a stay's nights).
  function refreshDays() {
    var days = [];
    var own = state.dayId && document.getElementById(state.dayId);
    if (own) days.push(own);
    if (state.anchor) {
      document.querySelectorAll("details.day-fold").forEach(function (d) {
        if (days.indexOf(d) < 0 && (d.querySelector("#" + CSS.escape(state.anchor)) ||
                                     d.querySelector('a[href="#' + state.anchor + '"]'))) days.push(d);
      });
    }
    return Promise.all(days.map(function (day) {
      return request(day.dataset.dayFragment).then(function (r) { return r.ok ? r.text() : null; }).then(function (html) {
        if (!html) return;
        var holder = document.createElement("div");
        holder.innerHTML = html.trim();
        var fresh = holder.querySelector("details.day-fold");
        if (!fresh) return;
        fresh.open = day.open;
        day.replaceWith(fresh);
      });
    })).then(function () {
      // Moved to a day that wasn't refreshed (a leg given another date): reload the page there.
      if (state.anchor && !state.deleted && !document.getElementById(state.anchor)) {
        location.hash = state.anchor;
        location.reload();
      }
    });
  }

  function afterPost(response) {
    var landed = new URL(response.url);
    if (response.status === 404) { state.deleted = true; close(); return refreshDays(); }
    if (!response.ok) { problem(response.status); return; }
    if (landed.searchParams.get("panel")) {
      return response.text().then(function (html) {
        render(html, landed.pathname + landed.search);
        if (response.redirected) { flashSaved(); refreshDays(); }
      });
    }
    // Saved, and the page sent us somewhere outside the panel (the trip page, the day page).
    flashSaved();
    return load(state.origin).then(refreshDays);
  }

  function open(href, opener) {
    state.opener = opener;
    state.deleted = false;
    state.tab = null;
    state.origin = entryUrl(href);
    var item = opener.closest("[data-panel]");
    state.anchor = item ? item.id : "";
    var day = opener.closest("details.day-fold");
    state.dayId = day ? day.id : "";
    panel.hidden = false;
    if (window.matchMedia("(max-width: 639px)").matches) document.body.style.overflow = "hidden";
    body.innerHTML = '<p class="text-sm text-zinc-500">Loading…</p>';
    heading.textContent = "";
    load(state.origin).then(function () { panel.querySelector("[data-panel-close]").focus(); });
  }

  function close() {
    panel.hidden = true;
    body.innerHTML = "";
    document.body.style.overflow = "";
    if (state.opener && document.body.contains(state.opener)) state.opener.focus && state.opener.focus();
  }

  document.addEventListener("click", function (event) {
    if (panel.contains(event.target) || event.defaultPrevented) return;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    var link = event.target.closest("a[data-panel-link]");
    if (link) { event.preventDefault(); open(link.getAttribute("href"), link); return; }
    var row = event.target.closest("[data-panel]");
    if (!row || event.target.closest("a, button, input, select, textarea, label, summary, form")) return;
    if (String(window.getSelection ? window.getSelection() : "").length) return;  // selecting text, not opening
    open(row.dataset.panel, row);
  });

  panel.querySelector("[data-panel-close]").addEventListener("click", close);
  document.addEventListener("keydown", function (event) {
    // Escape closes the panel, except inside the city box, where it closes the box's list.
    if (event.key === "Escape" && !panel.hidden && !event.target.closest("[data-city-search]")) close();
  });

  body.addEventListener("click", function (event) {
    var link = event.target.closest("a[href]");
    if (!link || event.defaultPrevented || link.target === "_blank" || link.hasAttribute("download")) return;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    var url = new URL(link.href);
    if (url.origin !== location.origin) return;
    if (url.pathname === tripPath) {  // back to the trip page (Cancel, a chip linking to Reference)
      event.preventDefault();
      close();
      if (url.hash) location.hash = url.hash;
      return;
    }
    if (url.pathname.indexOf("/trips/") !== 0 || /\/files\/\d+\/$|\.pdf$|\.ics$/.test(url.pathname)) return;
    event.preventDefault();
    var next = withPanel(link.href);
    load(next.pathname + next.search);
  });

  body.addEventListener("submit", function (event) {
    var form = event.target;
    var action = form.getAttribute("action");
    var url = new URL(action || state.current, location.href);
    if (url.origin !== location.origin) return;
    event.preventDefault();
    url.searchParams.set("panel", "1");
    var data;
    try { data = new FormData(form, event.submitter); } catch (e) {
      data = new FormData(form);
      if (event.submitter && event.submitter.name) data.append(event.submitter.name, event.submitter.value);
    }
    if ((form.getAttribute("method") || "get").toLowerCase() !== "post") {
      new URLSearchParams(data).forEach(function (value, key) { url.searchParams.set(key, value); });
      load(url.pathname + url.search);
      return;
    }
    request(url.pathname + url.search, { method: "POST", body: data }).then(afterPost);
  });
})();
