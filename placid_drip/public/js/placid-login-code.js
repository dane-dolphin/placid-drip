// ===== Login with an emailed 6-digit code (replaces frappe's "login with email link") =====
// Reuses frappe's #login-with-email-link section: step 1 asks for the email,
// step 2 for the code. Server side lives in placid_drip.login_code.
(function () {
  const section = document.querySelector("section.for-login-with-email-link");
  if (!section) return;

  const form = section.querySelector(".form-login-with-email-link");
  const emailField = form.querySelector(".email-field");
  const emailInput = form.querySelector("#login_with_email_link_email");
  const submitButton = form.querySelector("button[type=submit]");
  const cardBody = form.querySelector(".page-card-body");

  // Relabel right away (this script runs after the markup) so the old link wording doesn't flash.
  const LABEL = __("Login with Email Code");
  document.querySelectorAll("a.btn-login-with-email-link").forEach((a) => (a.textContent = LABEL));
  const heading = section.querySelector(".page-card-head h4");
  if (heading) heading.textContent = LABEL;

  // Step 2 markup, built with DOM calls so the email address is never parsed as HTML.
  const codeStep = document.createElement("div");
  codeStep.className = "placid-code-step";
  codeStep.hidden = true;

  const sentTo = document.createElement("p");
  sentTo.className = "placid-code-sent small";

  const codeInput = document.createElement("input");
  Object.assign(codeInput, {
    id: "login_code",
    className: "form-control placid-code-input",
    inputMode: "numeric",
    autocomplete: "one-time-code",
    maxLength: 6,
    placeholder: __("6-digit code"),
  });
  codeInput.setAttribute("aria-label", __("Login code"));

  const spamHint = document.createElement("p");
  spamHint.className = "small text-muted placid-code-hint";
  spamHint.textContent = __("Can't find the email? Check your Spam or Junk folder.");

  const links = document.createElement("p");
  links.className = "small placid-code-links";
  const resendLink = Object.assign(document.createElement("a"), { href: "#", textContent: __("Resend code") });
  const changeLink = Object.assign(document.createElement("a"), { href: "#", textContent: __("Use a different email") });
  links.append(resendLink, " · ", changeLink);

  codeStep.append(sentTo, codeInput, spamHint, links);
  cardBody.append(codeStep);

  const status = document.createElement("p");
  status.className = "placid-code-status small";
  status.setAttribute("role", "status");
  status.hidden = true;
  cardBody.append(status);

  let step = "email";
  let busy = false;

  function setStatus(message, isError) {
    status.textContent = message || "";
    status.hidden = !message;
    status.classList.toggle("text-danger", !!isError);
    status.classList.toggle("text-success", !isError);
  }

  function showStep(next, focus = true) {
    step = next;
    const onCode = next === "code";
    emailField.hidden = onCode;
    codeStep.hidden = !onCode;
    submitButton.textContent = onCode ? __("Verify and log in") : __("Email me a code");
    if (focus) (onCode ? codeInput : emailInput).focus();
  }

  function serverMessage(data) {
    try {
      const messages = JSON.parse(data._server_messages || "[]");
      if (messages.length) return JSON.parse(messages[0]).message;
    } catch (e) {
      // fall through to the caller's default
    }
    return null;
  }

  async function post(method, params) {
    const response = await fetch(`/api/method/${method}`, {
      method: "POST",
      headers: { Accept: "application/json", "X-Frappe-CSRF-Token": frappe.csrf_token },
      body: new URLSearchParams(params),
    });
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, data };
  }

  function fallbackError(status) {
    if (status === 429) return __("Too many requests from your network. Please try again later.");
    return __("Something went wrong. Please try again.");
  }

  async function sendCode() {
    const email = emailInput.value.trim();
    if (!email) {
      setStatus(__("Please enter your email address."), true);
      return;
    }
    const { ok, status: code, data } = await post("placid_drip.login_code.send_login_code", { email });
    if (!ok) {
      setStatus(serverMessage(data) || fallbackError(code), true);
      return;
    }
    sentTo.textContent = __("We sent a 6-digit code to {0}. It works for {1} minutes.", [
      email,
      (data.message && data.message.expires_in_minutes) || 10,
    ]);
    codeInput.value = "";
    setStatus("");
    showStep("code");
  }

  async function verifyCode() {
    const code = codeInput.value.trim();
    if (code.length !== 6) {
      setStatus(__("Please enter the 6-digit code from the email."), true);
      return;
    }
    const params = { email: emailInput.value.trim(), code };
    const redirectTo = new URLSearchParams(window.location.search).get("redirect-to");
    if (redirectTo) params.redirect_to = redirectTo;

    const { ok, status: httpStatus, data } = await post("placid_drip.login_code.verify_login_code", params);
    if (!ok) {
      setStatus(serverMessage(data) || fallbackError(httpStatus), true);
      codeInput.select();
      return;
    }
    setStatus(__("Logged in. Taking you to your courses…"), false);
    window.location.href = data.message || "/";
  }

  async function run(action) {
    if (busy) return;
    busy = true;
    submitButton.disabled = true;
    try {
      await action();
    } catch (e) {
      setStatus(__("Something went wrong. Please check your connection and try again."), true);
    } finally {
      busy = false;
      submitButton.disabled = false;
    }
  }

  codeInput.addEventListener("input", () => {
    codeInput.value = codeInput.value.replace(/\D/g, "").slice(0, 6);
    if (codeInput.value.length === 6) run(verifyCode);
  });

  resendLink.addEventListener("click", (event) => {
    event.preventDefault();
    run(async () => {
      await sendCode();
      if (!status.classList.contains("text-danger")) setStatus(__("Code sent again. Check your inbox."), false);
    });
  });

  changeLink.addEventListener("click", (event) => {
    event.preventDefault();
    setStatus("");
    showStep("email");
  });

  // frappe's login.js binds its own "send link" handler in frappe.ready; this
  // callback is registered later, so it runs after and can replace it.
  frappe.ready(() => {
    $(form)
      .off("submit")
      .on("submit", (event) => {
        event.preventDefault();
        run(step === "code" ? verifyCode : sendCode);
        return false;
      });
    showStep("email", false);
  });
})();
