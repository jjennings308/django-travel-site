// City admin: show only the regions of the chosen country in the Region select.
// Options carry data-country (CityAdminForm's RegionByCountrySelect). The country
// field is a select2 autocomplete, which fires jQuery "change", so listen via django.jQuery.
(function () {
  function init() {
    var country = document.getElementById("id_country");
    var region = document.getElementById("id_region");
    if (!country || !region) return;

    function filter() {
      var chosen = country.value;
      Array.prototype.forEach.call(region.options, function (opt) {
        if (!opt.value) {
          opt.textContent = chosen ? "---------" : "Choose a country first";
          return;
        }
        var show = chosen !== "" && opt.dataset.country === chosen;
        opt.hidden = !show;
        opt.disabled = !show;
      });
      var selected = region.options[region.selectedIndex];
      if (selected && selected.value && selected.hidden) region.value = "";
    }

    filter();
    if (window.django && django.jQuery) django.jQuery(country).on("change", filter);
    else country.addEventListener("change", filter);
  }
  document.addEventListener("DOMContentLoaded", init);
})();
