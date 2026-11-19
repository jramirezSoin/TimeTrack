// Arrastrar y soltar post-its entre estados (y al basurero = cerrada).
// Delegación sobre document: el tablero se reemplaza completo tras cada acción (htmx outerHTML).
(function () {
  var arrastrando = null;

  function zona(el) { return el && el.closest ? el.closest("[data-drop]") : null; }
  function limpiar() {
    document.querySelectorAll(".sobre").forEach(function (z) { z.classList.remove("sobre"); });
  }

  document.addEventListener("dragstart", function (e) {
    var nota = e.target.closest && e.target.closest(".postit");
    if (!nota) return;
    arrastrando = nota;
    e.dataTransfer.setData("text/plain", nota.dataset.id);
    e.dataTransfer.effectAllowed = "move";
    nota.classList.add("arrastrando");
    document.body.classList.add("arrastrando-nota");
  });

  document.addEventListener("dragend", function () {
    if (arrastrando) arrastrando.classList.remove("arrastrando");
    arrastrando = null;
    document.body.classList.remove("arrastrando-nota");
    limpiar();
  });

  document.addEventListener("dragover", function (e) {
    var z = zona(e.target);
    if (!arrastrando || !z) return;
    e.preventDefault();                      // permite soltar
    e.dataTransfer.dropEffect = "move";
    if (!z.classList.contains("sobre")) { limpiar(); z.classList.add("sobre"); }
  });

  document.addEventListener("dragleave", function (e) {
    var z = zona(e.target);
    if (z && !z.contains(e.relatedTarget)) z.classList.remove("sobre");
  });

  document.addEventListener("drop", function (e) {
    var z = zona(e.target);
    if (!arrastrando || !z) return;
    e.preventDefault();
    var id = arrastrando.dataset.id, estado = z.dataset.drop;
    var igual = arrastrando.dataset.estado === estado;
    limpiar();
    if (igual) return;                       // soltada en su misma columna: nada que hacer
    htmx.ajax("POST", "/tareas/" + encodeURIComponent(id) + "/mover", {
      source: "#tablero", target: "#tablero", swap: "outerHTML", values: { estado: estado }
    });
  });

  // El tablero se reemplaza entero: avisamos a lectores de pantalla de que cambió.
  document.body.addEventListener("htmx:afterSwap", function (e) {
    var ruta = e.detail && e.detail.pathInfo && e.detail.pathInfo.requestPath;
    if (ruta && ruta.indexOf("/tareas/") === 0 && window.anunciar) window.anunciar("Tablero actualizado.");
  });
})();
