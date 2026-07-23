/* Explicação de comunicação via IA (Monitoramento de Processos).
   Uso: CommExplainer.explain(url, container, btn) — faz o POST, renderiza o
   card estruturado no container e cuida de loading/erro. Todo texto vindo da
   IA entra via textContent (nunca innerHTML). */
window.CommExplainer = (function () {
  'use strict';

  var URGENCIA = {
    alta: { label: 'Urgência alta', cls: 'bg-danger-subtle text-danger-emphasis' },
    media: { label: 'Urgência média', cls: 'bg-warning-subtle text-warning-emphasis' },
    baixa: { label: 'Urgência baixa', cls: 'bg-secondary-subtle text-secondary-emphasis' }
  };

  var ACAO = {
    exige_acao: { label: 'Exige ação', cls: 'bg-danger-subtle text-danger-emphasis' },
    acao_facultativa: { label: 'Ação facultativa', cls: 'bg-warning-subtle text-warning-emphasis' },
    apenas_ciencia: { label: 'Apenas ciência', cls: 'bg-secondary-subtle text-secondary-emphasis' }
  };

  var TIPO_ATO = {
    sentenca: { label: 'Sentença', cls: 'bg-primary-subtle text-primary-emphasis' },
    acordao: { label: 'Acórdão', cls: 'bg-primary-subtle text-primary-emphasis' },
    decisao_interlocutoria: { label: 'Decisão interlocutória', cls: 'bg-info-subtle text-info-emphasis' },
    despacho: { label: 'Despacho', cls: 'bg-secondary-subtle text-secondary-emphasis' },
    ato_ordinatorio: { label: 'Ato ordinatório', cls: 'bg-secondary-subtle text-secondary-emphasis' },
    edital: { label: 'Edital', cls: 'bg-warning-subtle text-warning-emphasis' },
    audiencia: { label: 'Audiência', cls: 'bg-warning-subtle text-warning-emphasis' },
    outro: { label: 'Outro ato', cls: 'bg-secondary-subtle text-secondary-emphasis' }
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function badge(map, key) {
    var info = map[key] || { label: key || '—', cls: 'bg-secondary-subtle text-secondary-emphasis' };
    return el('span', 'badge ' + info.cls + ' me-1', info.label);
  }

  function render(container, payload) {
    var data = payload.data || {};
    container.innerHTML = '';

    var card = el('div', 'pm-explain');

    var badges = el('div', 'mb-2');
    if (data.tipo_ato) badges.appendChild(badge(TIPO_ATO, data.tipo_ato));
    badges.appendChild(badge(ACAO, data.acao_requerida));
    badges.appendChild(badge(URGENCIA, data.urgencia));
    card.appendChild(badges);

    if (data.tipo_ato_detalhe) {
      var ato = el('p', 'mb-2 small');
      ato.appendChild(el('strong', null, 'Ato comunicado: '));
      ato.appendChild(document.createTextNode(data.tipo_ato_detalhe));
      card.appendChild(ato);
    }

    if (data.resumo) card.appendChild(el('p', 'mb-2', data.resumo));

    if (data.acao_descricao) {
      var acao = el('p', 'mb-2 small');
      acao.appendChild(el('strong', null, 'O que fazer: '));
      acao.appendChild(document.createTextNode(data.acao_descricao));
      card.appendChild(acao);
    }

    if (data.prazo && data.prazo.existe) {
      var prazo = el('div', 'pm-explain-prazo mb-2');
      prazo.appendChild(el('div', 'fw-semibold small', 'Prazo'));
      if (data.prazo.descricao) prazo.appendChild(el('div', 'small', data.prazo.descricao));
      var partes = [];
      if (data.prazo.dias) partes.push(data.prazo.dias + ' dia(s) ' + (data.prazo.tipo_contagem === 'uteis' ? 'úteis' : (data.prazo.tipo_contagem === 'corridos' ? 'corridos' : '')));
      if (data.prazo.base_calculo) partes.push('contados de: ' + data.prazo.base_calculo);
      if (data.prazo.data_limite_estimada) partes.push('data-limite estimada: ' + data.prazo.data_limite_estimada);
      if (partes.length) prazo.appendChild(el('div', 'small text-body-secondary', partes.join(' · ')));
      card.appendChild(prazo);
    }

    if (data.datas_chave && data.datas_chave.length) {
      var datasWrap = el('div', 'mb-2');
      datasWrap.appendChild(el('div', 'fw-semibold small', 'Datas-chave'));
      data.datas_chave.forEach(function (d) {
        datasWrap.appendChild(el('div', 'small text-body-secondary', d.data + ' — ' + d.descricao));
      });
      card.appendChild(datasWrap);
    }

    if (data.papel_escritorio) {
      var papel = el('p', 'mb-2 small');
      papel.appendChild(el('strong', null, 'Papel do escritório: '));
      papel.appendChild(document.createTextNode(data.papel_escritorio));
      card.appendChild(papel);
    }

    if (data.urgencia_justificativa) {
      card.appendChild(el('p', 'mb-2 small text-body-secondary', data.urgencia_justificativa));
    }

    if (data.glossario && data.glossario.length) {
      var glos = el('div', 'mb-2');
      glos.appendChild(el('div', 'fw-semibold small', 'Termos'));
      data.glossario.forEach(function (g) {
        var linha = el('div', 'small text-body-secondary');
        linha.appendChild(el('em', null, g.termo));
        linha.appendChild(document.createTextNode(': ' + g.significado));
        glos.appendChild(linha);
      });
      card.appendChild(glos);
    }

    var rodape = 'Gerado por IA (' + (payload.model || 'modelo') + ') em ' + (payload.generated_at || '—') +
      ' — apoio à triagem; confira prazos e teor no processo oficial.';
    card.appendChild(el('div', 'small text-body-tertiary border-top pt-2', rodape));

    container.appendChild(card);
  }

  function explain(url, container, btn) {
    var originalHtml = btn ? btn.innerHTML : null;
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Explicando...';
    }
    container.innerHTML = '';

    return fetch(url, { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (resp) { return resp.json(); })
      .then(function (payload) {
        if (!payload.success) throw new Error(payload.message || 'Falha ao gerar a explicação.');
        render(container, payload);
        if (btn && !btn.hasAttribute('data-keep-visible')) btn.classList.add('d-none');
      })
      .catch(function (err) {
        var alerta = el('div', 'alert alert-warning small mb-0', err.message || 'Falha ao gerar a explicação.');
        container.appendChild(alerta);
      })
      .finally(function () {
        if (btn) {
          btn.disabled = false;
          if (originalHtml !== null) btn.innerHTML = originalHtml;
        }
      });
  }

  return { explain: explain, render: render };
})();
