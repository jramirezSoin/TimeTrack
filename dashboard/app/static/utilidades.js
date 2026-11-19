// Utilidades: botón «Copiar» (copia el <pre class="salida"> siguiente) y botón «Ahora» (epoch actual).
// Delegación sobre document: los resultados se reemplazan con htmx.
(function () {
  function copiar(texto) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(texto);
    return new Promise(function (ok, fallo) {          // respaldo para contextos sin Clipboard API
      var t = document.createElement("textarea");
      t.value = texto; t.style.position = "fixed"; t.style.opacity = "0";
      document.body.appendChild(t); t.select();
      try { document.execCommand("copy") ? ok() : fallo(); } catch (e) { fallo(e); }
      document.body.removeChild(t);
    });
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-copiar]");
    if (b) {
      var bloque = b.closest(".section-label");
      var pre = bloque && bloque.nextElementSibling;
      if (!pre) return;
      var original = b.innerHTML;
      function avisar(texto) {
        b.textContent = texto;
        if (window.anunciar) window.anunciar(texto);
        setTimeout(function () { b.innerHTML = original; }, 1400);
      }
      copiar(pre.textContent).then(function () { avisar("¡Copiado!"); }, function () { avisar("No se pudo copiar"); });
      return;
    }
    var a = e.target.closest("[data-ahora]");
    if (a) {
      var campo = document.getElementById(a.dataset.ahora);
      if (campo) campo.value = Math.floor(Date.now() / 1000);
    }
  });
})();
