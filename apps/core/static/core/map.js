// core/map.js — draws every <div data-sbl-map> on the page (templates/partials/_map.html).
//
// The page gives a GeoJSON URL (our own view) and a provider name. Each provider is an
// adapter with four functions, so another map service (e.g. Google Maps, which reads
// GeoJSON too) can be added here without touching views, data or templates:
//   create(el, opts)             -> map handle
//   addPoints(map, features)     -> pins, each with a popup card (feature.properties)
//   addRoute(map, coordinates)   -> a line through [lng, lat] points
//   addLegs(map, features)       -> LineString features (trip transport legs), styled by
//                                   properties.mode (plane: arc, train: solid, road: dashed)
//   fit(map, features)           -> zoom to show them all (points and lines)
// Feature properties: name, subtitle, url, image, order (a number for route stops), mode (legs).
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
    addPoints: function (map, features, opts) {
      var layer = (L.markerClusterGroup && !opts.route) ? L.markerClusterGroup({ showCoverageOnHover: false }) : L.layerGroup();
      features.forEach(function (f) {
        var ll = [f.geometry.coordinates[1], f.geometry.coordinates[0]];
        var marker;
        if (f.properties.order) {
          marker = L.marker(ll, { icon: L.divIcon({
            className: "", iconSize: [28, 28], iconAnchor: [14, 14],
            html: '<span style="display:flex;width:28px;height:28px;align-items:center;justify-content:center;border-radius:9999px;background:#8B5A3C;color:#fff;font:700 13px/1 sans-serif;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4)">' + Number(f.properties.order) + "</span>"
          }) });
        } else {
          marker = L.marker(ll);
        }
        marker.bindPopup(function () { return SBLMap.card(f.properties); });
        layer.addLayer(marker);
      });
      layer.addTo(map);
    },
    addLegs: function (map, features) {
      var styles = {
        plane: { color: "#2563eb", weight: 2.5, dashArray: "2 6" },
        train: { color: "#8B5A3C", weight: 4 },
        walking: { color: "#556B2F", weight: 3, dashArray: "1 6" }
      };
      var road = { color: "#C58B2A", weight: 3.5, dashArray: "8 6" };  // pov, rental car, other
      features.forEach(function (f) {
        var pts = f.geometry.coordinates.map(function (c) { return [c[1], c[0]]; });
        if (f.properties.mode === "plane" && pts.length === 2) pts = SBLMap.arc(pts[0], pts[1]);
        var line = L.polyline(pts, Object.assign({ opacity: 0.85 }, styles[f.properties.mode] || road));
        line.bindPopup(function () { return SBLMap.card(f.properties); });
        line.addTo(map);
      });
    },
    addRoute: function (map, coordinates) {
      L.polyline(coordinates.map(function (c) { return [c[1], c[0]]; }),
                 { color: "#8B5A3C", weight: 3, opacity: 0.8, dashArray: "6 6" }).addTo(map);
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

  function draw(el) {
    var provider = SBLMap.providers[el.dataset.provider];
    if (!provider || !provider.ready()) { status(el, "The map isn't available right now."); return; }
    fetch(el.dataset.url, { headers: { Accept: "application/geo+json, application/json" }, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        var all = (data.features || []).filter(function (f) { return f.geometry; });
        var features = all.filter(function (f) { return f.geometry.type === "Point"; });
        var legs = all.filter(function (f) { return f.geometry.type === "LineString"; });
        el.innerHTML = "";
        var opts = { tiles: el.dataset.tiles, attribution: el.dataset.attribution, route: el.dataset.route === "1" };
        var map = provider.create(el, opts);
        if (legs.length && provider.addLegs) provider.addLegs(map, legs);
        provider.addPoints(map, features, opts);
        if (opts.route && !legs.length) {  // no mapped legs: join the stops in order instead
          var stops = features.filter(function (f) { return f.properties.order; })
                              .sort(function (a, b) { return a.properties.order - b.properties.order; });
          if (stops.length > 1) provider.addRoute(map, stops.map(function (f) { return f.geometry.coordinates; }));
        }
        provider.fit(map, all);
      })
      .catch(function () { status(el, "The map couldn't be loaded."); });
  }

  function boot() { document.querySelectorAll("[data-sbl-map]").forEach(draw); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
