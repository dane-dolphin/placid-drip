// Show/hide toggle for the password field on the login page.
(function () {
  function bindShowPassword(root) {
    const toggles = (root || document).querySelectorAll(".toggle-password[toggle]");
    toggles.forEach((el) => {
      // prevent double-binding
      if (el.dataset.bound === "1") return;
      el.dataset.bound = "1";

      el.addEventListener("click", function () {
        const targetSel = el.getAttribute("toggle");
        if (!targetSel) return;

        const input = document.querySelector(targetSel);
        if (!input) return;

        const isPassword = input.getAttribute("type") === "password";
        input.setAttribute("type", isPassword ? "text" : "password");
        el.textContent = isPassword ? __("Hide") : __("Show");
      });
    });
  }

  // bind on initial load
  document.addEventListener("DOMContentLoaded", () => bindShowPassword(document));

  // in case frappe replaces login dom / rerenders (safe)
  setTimeout(() => bindShowPassword(document), 250);
})();