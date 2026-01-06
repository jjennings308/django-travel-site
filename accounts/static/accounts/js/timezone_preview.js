(function () {
  function formatInTZ(tz) {
    // If tz is invalid, this throws RangeError
    const now = new Date();
    return now.toLocaleString(undefined, {
      timeZone: tz,
      weekday: "short",
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function findHelpTextEl(select) {
    // Django admin help text can be in different places depending on version/theme.
    // Try a few common patterns near the field container.
    const fieldContainer =
      select.closest(".form-row") ||
      select.closest(".fieldBox") ||
      select.closest(".field-timezone") ||
      select.closest(".field-time_zone") ||
      select.parentElement;

    if (!fieldContainer) return null;

    return (
      fieldContainer.querySelector(".help") ||
      fieldContainer.querySelector(".helptext") ||
      fieldContainer.querySelector(".help-text") ||
      fieldContainer.querySelector("div.help") ||
      fieldContainer.querySelector("p.help") ||
      null
    );
  }

  function updatePreview(select) {
    if (!select || !select.value) return;

    let formatted;
    try {
      formatted = formatInTZ(select.value);
    } catch (e) {
      // Invalid timezone in browser
      formatted = null;
    }

    const helpEl = findHelpTextEl(select);
    if (!helpEl) return;

    const base = "IANA timezone (e.g. America/New_York).";
    helpEl.textContent = formatted
      ? `${base} Current local time: ${formatted}`
      : base;
  }

  function wireSelect(select) {
    updatePreview(select);
    select.addEventListener("change", function () {
      updatePreview(select);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    // Match both:
    // - standalone: name="timezone"
    // - inline formsets: name like "...-timezone"
    const selects = document.querySelectorAll('select[name="timezone"], select[name$="-timezone"]');
    if (!selects.length) return;

    selects.forEach(wireSelect);
  });
})();
