// ===== Cursor follower with easing (Login page only) =====
(() => {
  if (!document.body.dataset.path || document.body.dataset.path !== "login") return;

  // Disable on touch devices
  if ("ontouchstart" in window) return;

  const ring = document.createElement("div");
  ring.className = "cursor-ring";
  const dot = document.createElement("div");
  dot.className = "cursor-dot";
  ring.appendChild(dot)
  document.body.appendChild(ring);

  let mouseX = 0, mouseY = 0;
  let ringX = 0, ringY = 0;

  const speed = 0.15; // smaller = more delay / smoother

  document.addEventListener("mousemove", (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;
    document.body.classList.add("cursor-active");
  });

  document.addEventListener("mouseleave", () => {
    document.body.classList.remove("cursor-active");
  });

  document.addEventListener("mousedown", () => {
    ring.classList.add("cursor-click");
  });

  document.addEventListener("mouseup", () => {
    ring.classList.remove("cursor-click");
  });

  function animate() {
    ringX += (mouseX - ringX) * speed;
    ringY += (mouseY - ringY) * speed;

    ring.style.transform = `translate(${ringX}px, ${ringY}px) translate(-50%, -50%)`;

    requestAnimationFrame(animate);
  }

  animate();
})();


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