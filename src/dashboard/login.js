const form = document.getElementById("login-form");
const errorBox = document.getElementById("error");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.textContent = "";
  try {
    const res = await fetch("/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: document.getElementById("username").value,
        password: document.getElementById("password").value,
      }),
    });
    if (res.ok) {
      window.location.href = "/";
      return;
    }
    errorBox.textContent =
      res.status === 401 ? "Incorrect username or password." : "Sign-in failed. Try again.";
  } catch (err) {
    errorBox.textContent = "Could not reach the server.";
  }
});
