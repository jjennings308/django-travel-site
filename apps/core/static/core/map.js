// core/map.js — draws every <div data-sbl-map> on the page (templates/partials/_map.html).
//
// The page gives a GeoJSON URL (our own view) and a provider name. Each provider is an
// adapter with four functions, so another map service (e.g. Google Maps, which reads
// GeoJSON too) can be added here without touching views, data or templates:
//   create(el, opts)             -> map handle
//   addPoints(map, features)     -> pins, each with a popup card (feature.properties)
//   addRoute(map, coordinates)   -> a line through [lng, lat] points
//   fit(map, features)           -> zoom to show them all
// Feature properties: name, subtitle, url, image, order (a number for route stops).
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

  // ---- OpenStreetMap through Leaflet -----------------------------------------------------
  SBLMap.providers.osm = {
    ready: function () { return !!window.L; },
    create: function (el, opts) {
      var map = L.map(el, { scrollWheelZoom: false });
      L.tileLayer(opts.tiles, { maxZoom: 19, attribution: opts.attribution }).addTo(map);
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
    addRoute: function (map, coordinates) {
      L.polyline(coordinates.map(function (c) { return [c[1], c[0]]; }),
                 { color: "#8B5A3C", weight: 3, opacity: 0.8, dashArray: "6 6" }).addTo(map);
    },
    fit: function (map, features) {
      if (!features.length) { map.setView([20, 0], 2); return; }
      var bounds = L.latLngBounds(features.map(function (f) { return [f.geometry.coordinates[1], f.geometry.coordinates[0]]; }));
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
        var features = (data.features || []).filter(function (f) { return f.geometry && f.geometry.type === "Point"; });
        el.innerHTML = "";
        var opts = { tiles: el.dataset.tiles, attribution: el.dataset.attribution, route: el.dataset.route === "1" };
        var map = provider.create(el, opts);
        provider.addPoints(map, features, opts);
        if (opts.route) {
          var stops = features.filter(function (f) { return f.properties.order; })
                              .sort(function (a, b) { return a.properties.order - b.properties.order; });
          if (stops.length > 1) provider.addRoute(map, stops.map(function (f) { return f.geometry.coordinates; }));
        }
        provider.fit(map, features);
      })
      .catch(function () { status(el, "The map couldn't be loaded."); });
  }

  function boot() { document.querySelectorAll("[data-sbl-map]").forEach(draw); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
