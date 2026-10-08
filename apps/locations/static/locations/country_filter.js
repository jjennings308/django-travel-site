// Show only the options of the chosen country in every <select data-country-source="id_…">
// (CountryTaggedSelect tags each option with data-country). With no country chosen,
// every option shows. A choice that no longer fits is cleared. Select2 (the admin's
// autocomplete) fires jQuery "change", so listen through django.jQuery when present.
(function () {
  function bind(target) {
    var source = document.getElementById(target.dataset.countrySource);
    if (!source) return;
    function filter() {
      var chosen = source.value;
      Array.prototype.forEach.call(target.options, function (opt) {
        if (!opt.value) return;
        var show = !chosen || opt.dataset.country === chosen;
        opt.hidden = !show;
        opt.disabled = !show;
      });
      var selected = target.options[target.selectedIndex];
      if (selected && selected.value && selected.hidden) target.value = "";
    }
    filter();
    if (window.django && django.jQuery) django.jQuery(source).on("change", filter);
    else source.addEventListener("change", filter);
  }
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("select[data-country-source]").forEach(bind);
  });
})();
