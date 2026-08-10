/*
 * Render da célula de protocolo administrativo (FAP Web) nas listagens
 * DataTables do Centro de Contestações.
 *
 * A fonte do número é `FapWebContestacao` (Painel FAP); o backend entrega em
 * cada linha o campo `fap_protocols`, já agrupado por protocolo e ordenado por
 * instância — ver `_fap_protocols_for_vigencias` em
 * app/blueprints/disputes_center.py.
 *
 * Uso:
 *   render: (data) => window.renderFapProtocolCell(data)
 *
 * O link para o Painel FAP sai de `window.fapPanelProtocolUrl`, que cada
 * template define via Jinja e só preenche quando o usuário tem o módulo
 * `fap_panel` — sem ele o protocolo aparece como texto, sem link. Dá para
 * sobrescrever por chamada com `{ panelUrl: '...' }`.
 *
 * Estilos em static/css/fap-protocol-cell.css.
 */
(function (global) {
  'use strict';

  function escapeHtml(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function renderFapProtocolCell(protocols, options) {
    var opts = options || {};
    var list = Array.isArray(protocols) ? protocols : [];
    var panelUrl = opts.panelUrl !== undefined ? opts.panelUrl : global.fapPanelProtocolUrl;

    if (!list.length) {
      var vazio = opts.emptyTitle
        || 'Nenhuma contestação do FAP Web sincronizada para este CNPJ nesta vigência.';
      return '<span class="protocol-empty" data-bs-toggle="tooltip" title="'
        + escapeHtml(vazio) + '">—</span>';
    }

    var itens = list.map(function (proto) {
      var numero = escapeHtml(proto.protocolo_formatado || proto.protocolo || '');
      var instancia = escapeHtml(proto.instancias_label || '');
      var detalhe = proto.detalhe || '';
      var corpo;

      if (panelUrl && proto.protocolo) {
        corpo = '<a class="protocol-code" href="' + escapeHtml(panelUrl)
          + encodeURIComponent(proto.protocolo)
          + '" data-bs-toggle="tooltip" title="'
          + escapeHtml(detalhe ? detalhe + ' · ver no Painel FAP' : 'Ver no Painel FAP')
          + '">' + numero + '</a>';
      } else {
        corpo = '<span class="protocol-code" data-bs-toggle="tooltip" title="'
          + escapeHtml(detalhe) + '">' + numero + '</span>';
      }

      return '<div class="protocol-item">'
        + '<span class="protocol-instance">' + instancia + '</span>'
        + corpo
        + '</div>';
    });

    return '<div class="protocol-list">' + itens.join('') + '</div>';
  }

  global.renderFapProtocolCell = renderFapProtocolCell;
})(window);
