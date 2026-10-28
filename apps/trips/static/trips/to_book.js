// Mark done in place (booking-todos K2), on the trip page's To book and the To do page: a form with
// data-mark-done is posted by fetch; trips:task_done answers 204. On the trip page the row greys and
// moves to "Done today" (until the page is reloaded); on the To do page it greys where it is. Without
// JavaScript the form posts and the page comes back as before.
(function () {
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.matches || !form.matches("form[data-mark-done]")) return;
    event.preventDefault();
    var button = form.querySelector("button");
    if (button) button.disabled = true;
    fetch(form.getAttribute("action"), {
      method: "POST", body: new FormData(form), credentials: "same-origin",
      headers: { "X-Requested-With": "fetch" },
    }).then(function (response) {
      if (response.status !== 204) { form.submit(); return; }
      var task = form.closest("[data-to-book-task]");
      var row = form.closest("[data-to-book-row], li");
      var list = form.closest("[data-to-book]");
      var done = list && list.querySelector("[data-done-today]");
      if (task && row && row.querySelectorAll("[data-to-book-task]").length > 1) {
        task.classList.add("opacity-50", "line-through");  // one of several to-dos on the item
        form.remove();
        return;
      }
      if (row) {
        row.classList.add("opacity-50");
        row.removeAttribute("data-panel");
        form.remove();
        if (done) {
          done.hidden = false;
          done.querySelector("ul").appendChild(row);
        }
      }
    }).catch(function () { form.submit(); });
  });
})();
