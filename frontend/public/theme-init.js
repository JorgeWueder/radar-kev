// Aplica el tema antes del primer pintado para evitar el destello (archivo externo: compatible con CSP).
try {
  var t = localStorage.getItem("theme");
  var dark = t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  if (dark) document.documentElement.classList.add("dark");
} catch (e) {}
