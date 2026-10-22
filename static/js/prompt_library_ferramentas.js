/* Modal das ferramentas do conector (Biblioteca de IA): busca, filtro por área e,
 * no modo "inserir", o clique no card avisa o editor pelo evento
 * `plb:inserir-ferramenta` (detail = nome da ferramenta). */
(function () {
  'use strict';

  function semAcento(t) {
    return (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
      .replace(/[^a-z0-9\s]+/g, '');  // sem pontuação: "email" acha "E-mail"
  }

  document.querySelectorAll('.plb-modal-ferramentas').forEach(function (modal) {
    var busca = modal.querySelector('[data-fm-busca]');
    var chips = modal.querySelectorAll('[data-fm-area]');
    var cards = Array.prototype.slice.call(modal.querySelectorAll('.plb-fc'));
    var vazio = modal.querySelector('[data-fm-vazio]');
    var area = '';
    cards.forEach(function (c) { c._busca = semAcento(c.dataset.busca); });

    function aplicar() {
      var termos = semAcento(busca.value).split(/\s+/).filter(Boolean);
      var n = 0;
      cards.forEach(function (c) {
        var ok = (!area || c.dataset.area === area) && termos.every(function (t) { return c._busca.indexOf(t) >= 0; });
        c.hidden = !ok;
        if (ok) n++;
      });
      vazio.hidden = n > 0;
      chips.forEach(function (b) { b.classList.toggle('active', b.dataset.fmArea === area); });
    }

    busca.addEventListener('input', aplicar);
    chips.forEach(function (b) {
      b.addEventListener('click', function () { area = b.dataset.fmArea; aplicar(); });
    });
    // Cada abertura começa com a lista inteira.
    modal.addEventListener('show.bs.modal', function () { busca.value = ''; area = ''; aplicar(); });
    // setTimeout: o AdminLTE foca o X da janela depois deste ouvinte.
    modal.addEventListener('shown.bs.modal', function () { setTimeout(function () { busca.focus(); }, 0); });

    if (modal.dataset.modo === 'inserir') {
      modal.addEventListener('click', function (e) {
        var card = e.target.closest('[data-fm-inserir]');
        if (!card) return;
        document.dispatchEvent(new CustomEvent('plb:inserir-ferramenta', { detail: card.dataset.fmInserir }));
        bootstrap.Modal.getOrCreateInstance(modal).hide();
      });
    }
  });
})();
