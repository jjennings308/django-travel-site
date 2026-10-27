// core/map.js — draws every <div data-sbl-map> on the page (templates/partials/_map.html).
//
// The page gives GeoJSON URLs (our own views: data-url plus optional data-extra-urls) and a
// provider name. Each provider is an adapter with these functions, so another map service
// (e.g. Google Maps, which reads GeoJSON too) can be added here without touching views,
// data or templates:
//   create(el, opts)                -> map handle
//   group(map)                      -> a container for one layer, shown on the map
//   addPoints(map, group, features, opts) -> pins with a popup card (feature.properties)
//   addLegs(map, group, features)   -> LineString features (trip transport legs), styled by
//                                      properties.mode (plane: arc, train: solid, road: dashed)
//   addRoute(map, group, coordinates) -> a line through [lng, lat] points
//   toggle(map, group, visible)     -> show or hide a layer
//   fit(map, features)              -> zoom to show them all (points and lines)
// Feature properties: name, subtitle, url, image, order (route stops), mode and planned (legs: fainter),
// layer (which switch it belongs to, default "places"), marker ("poi": small dot, "stay": house,
// "idea": faint dashed dot for the trip's Ideas shelf).
// Layer switches: <input type="checkbox" data-layer="cities"> inside the element named by
// data-controls; a layer with nothing to show disables its switch.
// Text from the catalogue is user-submitted, so popups are built with DOM methods only.
(function () {
  "use strict";
  var SBLMap = window.SBLMap = window.SBLMap || { providers: {} };

  // ---- the popup card (shared by every provider) --------------------------------------
  SBLMap.card = function (props) {
    var box = document.createElement("div");
    box.style.width = "14rem";
    if (props.image) {
      var img = document.createElement("img");
      img.src = props.image;
      img.alt = "";
      img.loading = "lazy";
      img.style.cssText = "width:100%;height:7rem;object-fit:cover;border-radius:.5rem;margin-bottom:.4rem";
      box.appendChild(img);
    }
    var title = document.createElement("strong");
    title.textContent = (props.order ? props.order + ". " : "") + (props.name || "");
    box.appendChild(title);
    if (props.subtitle) {
      var sub = document.createElement("div");
      sub.textContent = props.subtitle;
      sub.style.cssText = "color:#6b6157;font-size:.8rem;margin-top:.1rem";
      box.appendChild(sub);
    }
    if (props.url) {
      var link = document.createElement("a");
      link.href = props.url;
      link.textContent = "Open →";
      link.style.cssText = "display:inline-block;margin-top:.35rem;font-weight:600";
      box.appendChild(link);
    }
    return box;
  };

  // ---- geometry helpers (provider-neutral) ------------------------------------------------
  // Every [lng, lat] position in the features (points and line vertices).
  SBLMap.positions = function (features) {
    var out = [];
    features.forEach(function (f) {
      if (f.geometry.type === "Point") out.push(f.geometry.coordinates);
      else if (f.geometry.type === "LineString") out = out.concat(f.geometry.coordinates);
    });
    return out;
  };
  // A gentle arc between two [lat, lng] points (for flights), as [lat, lng] points.
  SBLMap.arc = function (a, b) {
    var mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    var dx = b[1] - a[1], dy = b[0] - a[0];
    var bend = 0.18;  // how far the curve bows out, as a share of the distance
    var ctrl = [mid[0] + dx * bend, mid[1] - dy * bend];
    var out = [];
    for (var i = 0; i <= 24; i++) {
      var t = i / 24, u = 1 - t;
      out.push([u * u * a[0] + 2 * u * t * ctrl[0] + t * t * b[0], u * u * a[1] + 2 * u * t * ctrl[1] + t * t * b[1]]);
    }
    return out;
  };

  // ---- OpenStreetMap through Leaflet -----------------------------------------------------
  SBLMap.providers.osm = {
    ready: function () { return !!window.L; },
    create: function (el, opts) {
      var map = L.map(el, { scrollWheelZoom: false });
      // OpenStreetMap's tile policy requires a Referer naming the site. The site-wide policy is
      // "same-origin" (no Referer to other sites), so tiles alone send the origin only
      // (https://sharebucketlist.com/, never the page path); without it the tiles are blocked.
      L.tileLayer(opts.tiles, { maxZoom: 19, attribution: opts.attribution,
                                referrerPolicy: "strict-origin-when-cross-origin" }).addTo(map);
      map.on("focus", function () { map.scrollWheelZoom.enable(); });
      map.on("blur", function () { map.scrollWheelZoom.disable(); });
      return map;
    },
    group: function (map) { return L.layerGroup().addTo(map); },
    toggle: function (map, group, visible) {
      if (visible) { if (!map.hasLayer(group)) group.addTo(map); } else { map.removeLayer(group); }
    },
    addPoints: function (map, group, features, opts) {
      var layer = (L.markerClusterGroup && !opts.route) ? L.markerClusterGroup({ showCoverageOnHover: false }) : L.layerGroup();
      features.forEach(function (f) {
        var ll = [f.geometry.coordinates[1], f.geometry.coordinates[0]];
        var marker;
        if (f.properties.order) {
          marker = L.marker(ll, { icon: L.divIcon({
            className: "", iconSize: [28, 28], iconAnchor: [14, 14],
            html: '<span style="display:flex;width:28px;height:28px;align-items:center;justify-content:center;border-radius:9999px;background:#8B5A3C;color:#fff;font:700 13px/1 sans-serif;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4)">' + Number(f.properties.order) + "</span>"
          }) });
        } else if (f.properties.marker === "stay") {
          marker = L.marker(ll, { icon: L.divIcon({
            className: "", iconSize: [26, 26], iconAnchor: [13, 13],
            html: '<span style="display:flex;width:26px;height:26px;align-items:center;justify-content:center;border-radius:6px;background:#7c3aed;color:#fff;font-size:14px;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.45)"><i class="bi bi-house-door-fill"></i></span>'
          }) });
        } else if (f.properties.marker === "poi") {
          marker = L.marker(ll, { icon: L.divIcon({
            className: "", iconSize: [16, 16], iconAnchor: [8, 8],
            html: '<span style="display:block;width:16px;height:16px;border-radius:9999px;background:#16a34a;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.45)"></span>'
          }) });
        } else if (f.properties.marker === "idea") {
          marker = L.marker(ll, { opacity: 0.75, icon: L.divIcon({
            className: "", iconSize: [14, 14], iconAnchor: [7, 7],
            html: '<span style="display:block;width:14px;height:14px;border-radius:9999px;background:#fbbf24;border:2px dashed #b45309"></span>'
          }) });
        } else {
          marker = L.marker(ll);
        }
        marker.bindPopup(function () { return SBLMap.card(f.properties); });
        layer.addLayer(marker);
      });
      group.addLayer(layer);
    },
    addLegs: function (map, group, features) {
      var styles = {
        plane: { color: "#2563eb", weight: 2.5, dashArray: "2 6" },
        train: { color: "#8B5A3C", weight: 4 },
        walking: { color: "#556B2F", weight: 3, dashArray: "1 6" }
      };
      var road = { color: "#C58B2A", weight: 3.5, dashArray: "8 6" };  // pov, rental car, other
      features.forEach(function (f) {
        var pts = f.geometry.coordinates.map(function (c) { return [c[1], c[0]]; });
        if (f.properties.mode === "plane" && pts.length === 2) pts = SBLMap.arc(pts[0], pts[1]);
        var line = L.polyline(pts, Object.assign({ opacity: f.properties.planned ? 0.45 : 0.85 }, styles[f.properties.mode] || road));
        line.bindPopup(function () { return SBLMap.card(f.properties); });
        group.addLayer(line);
      });
    },
    addRoute: function (map, group, coordinates) {
      group.addLayer(L.polyline(coordinates.map(function (c) { return [c[1], c[0]]; }),
                                { color: "#8B5A3C", weight: 3, opacity: 0.8, dashArray: "6 6" }));
    },
    fit: function (map, features) {
      var pts = SBLMap.positions(features);
      if (!pts.length) { map.setView([20, 0], 2); return; }
      var bounds = L.latLngBounds(pts.map(function (c) { return [c[1], c[0]]; }));
      map.fitBounds(bounds, { padding: [30, 30], maxZoom: 12 });
    }
  };

  // ---- boot -------------------------------------------------------------------------------
  function status(el, text) {
    var p = el.querySelector("[data-sbl-map-status]");
    if (p) p.textContent = text;
  }

  function load(url) {
    return fetch(url, { headers: { Accept: "application/geo+json, application/json" }, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function draw(el) {
    var provider = SBLMap.providers[el.dataset.provider];
    if (!provider || !provider.ready()) { status(el, "The map isn't available right now."); return; }
    var extra = (el.dataset.extraUrls || "").split(" ").filter(Boolean);
    // The main data must load; an extra source that fails just leaves its layer empty.
    Promise.all([load(el.dataset.url)].concat(extra.map(function (u) { return load(u).catch(function () { return {}; }); })))
      .then(function (results) {
        var all = [];
        results.forEach(function (data) { all = all.concat((data.features || []).filter(function (f) { return f.geometry; })); });
        el.innerHTML = "";
        var opts = { tiles: el.dataset.tiles, attribution: el.dataset.attribution, route: el.dataset.route === "1" };
        var map = provider.create(el, opts);
        var hasLegs = all.some(function (f) { return f.geometry.type === "LineString"; });
        var layers = {};
        all.forEach(function (f) {
          var name = f.properties.layer || "places";
          (layers[name] = layers[name] || []).push(f);
        });
        var groups = {};
        Object.keys(layers).forEach(function (name) {
          var group = groups[name] = provider.group(map);
          var points = layers[name].filter(function (f) { return f.geometry.type === "Point"; });
          var lines = layers[name].filter(function (f) { return f.geometry.type === "LineString"; });
          if (lines.length) provider.addLegs(map, group, lines);
          if (points.length) provider.addPoints(map, group, points, opts);
          if (opts.route && !hasLegs) {  // no mapped legs: join the numbered stops in order instead
            var stops = points.filter(function (f) { return f.properties.order; })
                              .sort(function (a, b) { return a.properties.order - b.properties.order; });
            if (stops.length > 1) provider.addRoute(map, group, stops.map(function (f) { return f.geometry.coordinates; }));
          }
        });
        var controls = el.dataset.controls && document.getElementById(el.dataset.controls);
        if (controls) {
          controls.querySelectorAll("input[data-layer]").forEach(function (input) {
            var group = groups[input.dataset.layer];
            if (!group) {
              input.checked = false;
              input.disabled = true;
              var label = input.closest("label");
              if (label) { label.classList.add("opacity-50"); label.title = "Nothing to show on this trip yet"; }
              return;
            }
            provider.toggle(map, group, input.checked);
            input.addEventListener("change", function () { provider.toggle(map, group, input.checked); });
          });
        }
        provider.fit(map, all);
      })
      .catch(function () { status(el, "The map couldn't be loaded."); });
  }

  function boot() { document.querySelectorAll("[data-sbl-map]").forEach(draw); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
