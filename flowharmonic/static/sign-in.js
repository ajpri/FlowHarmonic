"use strict";
const form = document.getElementById("sign-in-form");
const status = document.getElementById("sign-in-status");
const error = document.getElementById("sign-in-error");
const password = document.getElementById("password");
const submit = document.getElementById("sign-in-submit");
async function loadSignIn() {
  try {
    const response = await fetch("/api/auth", {cache: "no-store", credentials: "same-origin", signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error("Could not load sign-in. Reload to try again.");
    const auth = await response.json();
    if (auth.authenticated) { location.replace("/"); return; }
    form.hidden = !auth.configured;
    status.textContent = auth.configured ? "" : "Set the management password on this device: sudo flowharmonic password";
    status.hidden = auth.configured;
  } catch (problem) { status.textContent = problem.message || "Could not load sign-in. Reload to try again."; }
}
form.addEventListener("submit", async event => {
  event.preventDefault();
  submit.disabled = true;
  error.hidden = true;
  try {
    const response = await fetch("/api/auth/sign-in", {
      method: "POST", credentials: "same-origin", signal: AbortSignal.timeout(30000),
      headers: {"Content-Type": "application/json", "X-FlowHarmonic-Request": "1"},
      body: JSON.stringify({password: password.value}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Could not sign in. Check the password and try again.");
    location.replace("/");
  } catch (problem) {
    error.textContent = problem.name === "TimeoutError" || problem.name === "AbortError" ?
      "Sign-in took too long. Try again." : problem.message || "Could not sign in. Check the connection and try again.";
    error.hidden = false;
  } finally {
    password.value = "";
    submit.disabled = false;
  }
});
loadSignIn();
