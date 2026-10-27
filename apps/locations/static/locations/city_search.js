// The city search box (locations.widgets.CitySearchInput; day-first plan, P1). An Alpine component:
// type to search locations:city_search, pick a result or one of the trip's cities, or add a city
// that isn't listed (locations:city_new). The hidden input carries the id and the city's zone
// (data-tz) and fires "change" when it changes, for the leg page's zone fill.
(function () {
  if (window.sblCitySearch) return;
  window.sblCitySearch = true;

  function csrfToken(el) {
    var form = el.closest("form");
    var input = form && form.querySelector('input[name="csrfmiddlewaretoken"]');
    if (input) return input.value;
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("citySearch", function (configId) {
      var config = JSON.parse(document.getElementById(configId).textContent);
      return {
        name: config.name,
        multiple: config.multiple,
        selected: config.selected,
        chips: config.chips,
        q: "",
        results: [],
        open: false,
        active: -1,
        busy: false,
        adding: false,
        countries: [],
        regions: [],
        draft: { name: "", country: "", region: "" },
        error: "",
        seq: 0,

        get value() { return this.multiple || !this.selected.length ? "" : this.selected[0].id; },
        get timezone() { return this.multiple || !this.selected.length ? "" : (this.selected[0].timezone || ""); },

        search: function () {
          var q = this.q.trim(), self = this, seq = ++this.seq;
          this.active = -1;
          if (!q) { this.results = []; return; }
          this.busy = true;
          this.open = true;
          fetch(config.searchUrl + "?q=" + encodeURIComponent(q), { headers: { "X-Requested-With": "fetch" } })
            .then(function (r) { return r.ok ? r.json() : { results: [] }; })
            .then(function (data) { if (seq === self.seq) { self.results = data.results; self.busy = false; } })
            .catch(function () { if (seq === self.seq) self.busy = false; });
        },
        move: function (step) {
          if (!this.results.length) return;
          this.open = true;
          this.active = (this.active + step + this.results.length) % this.results.length;
        },
        choose: function () {
          if (this.active >= 0 && this.results[this.active]) this.pick(this.results[this.active]);
          else if (this.results.length === 1) this.pick(this.results[0]);
        },
        pick: function (city) {
          var picked = { id: String(city.id), label: city.label, timezone: city.timezone || "" };
          if (this.multiple) {
            if (!this.selected.some(function (c) { return c.id === picked.id; })) this.selected.push(picked);
          } else {
            this.selected = [picked];
          }
          this.q = "";
          this.results = [];
          this.open = false;
          this.adding = false;
          this.changed();
        },
        remove: function (city) {
          this.selected = this.selected.filter(function (c) { return c.id !== city.id; });
          this.changed();
        },
        clear: function () { this.selected = []; this.changed(); },
        changed: function () {
          var input = this.$refs.value;
          this.$nextTick(function () { input.dispatchEvent(new Event("change", { bubbles: true })); });
        },

        startNew: function () {
          var self = this;
          this.draft = { name: this.q.trim(), country: "", region: "" };
          this.error = "";
          this.adding = true;
          this.open = false;
          if (!this.countries.length) {
            fetch(config.countriesUrl, { headers: { "X-Requested-With": "fetch" } })
              .then(function (r) { return r.json(); })
              .then(function (data) { self.countries = data.countries; });
          }
        },
        loadRegions: function () {
          var self = this;
          this.regions = [];
          this.draft.region = "";
          if (!this.draft.country) return;
          fetch(config.regionsUrl.replace("/0/", "/" + this.draft.country + "/"), { headers: { "X-Requested-With": "fetch" } })
            .then(function (r) { return r.json(); })
            .then(function (data) { self.regions = data.regions; });
        },
        saveNew: function () {
          var self = this, body = new FormData();
          if (!this.draft.name.trim() || !this.draft.country) { this.error = "Give the city a name and a country."; return; }
          body.append("name", this.draft.name);
          body.append("country", this.draft.country);
          body.append("region", this.draft.region);
          this.busy = true;
          this.error = "";
          fetch(config.newUrl, { method: "POST", body: body,
                                 headers: { "X-Requested-With": "fetch", "X-CSRFToken": csrfToken(this.$el) } })
            .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
            .then(function (res) {
              self.busy = false;
              if (res.ok && res.data.city) { self.pick(res.data.city); return; }
              var errors = (res.data && res.data.errors) || {};
              var first = Object.keys(errors)[0];
              self.error = first ? errors[first][0].message : "That city couldn't be added.";
            })
            .catch(function () { self.busy = false; self.error = "That city couldn't be added. Try again."; });
        },
      };
    });
  });
})();
