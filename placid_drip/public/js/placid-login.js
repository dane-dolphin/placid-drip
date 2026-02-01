// ===== Cursor follower with easing (Login page only) =====
(() => {
  if (!document.body.dataset.path || document.body.dataset.path !== "login") return;

  // Disable on touch devices
  if ("ontouchstart" in window) return;

  const ring = document.createElement("div");
  ring.className = "cursor-ring";
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

  function animate() {
    ringX += (mouseX - ringX) * speed;
    ringY += (mouseY - ringY) * speed;

    ring.style.transform = `translate(${ringX}px, ${ringY}px) translate(-50%, -50%)`;

    requestAnimationFrame(animate);
  }

  animate();
})();