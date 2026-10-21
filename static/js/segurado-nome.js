/*
 * Nome do segurado e botão "Revelar nome" — telas de Benefícios da Central e
 * do cálculo FAP.
 *
 * O FAP não informa nome. O botão chama a consulta paga por CPF (uma vez por
 * CPF — a resposta fica em `segurado_nomes` e vale para todas as telas); ver
 * app/services/segurado_nome_service.py.
 *
 * Uso:
 *   window.renderSeguradoNome(nomeRevelado, { cpf, podeRevelar, url })
 * devolve o HTML de um `.js-nome-segurado`. O clique no botão é tratado aqui
 * por delegação, então funciona em linha desenhada pelo DataTables e em linha
 * vinda do servidor.
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

  function conteudo(info, opts) {
    if (info && info.status === 'encontrado') {
      const aviso = info.nascimento_diverge
        ? ' <i class="bi bi-exclamation-triangle-fill text-warning" title="A data de nascimento da consulta não bate com a do FAP — pode ser outra pessoa. Confira antes de usar."></i>'
        : '';
      return `<span class="fw-semibold">${escapeHtml(info.nome)}</span>`
        + ` <i class="bi bi-person-check text-success small" title="Nome obtido por consulta de CPF (o FAP não informa nome)"></i>${aviso}`;
    }
    if (info && info.status === 'nao_encontrado') {
      return '<span class="text-muted small" title="A consulta de CPF não encontrou este CPF">Nome não encontrado</span>';
    }
    if (opts && opts.podeRevelar && opts.cpf && opts.url) {
      return `<button type="button" class="btn btn-outline-primary btn-sm py-0 px-2 js-revelar-nome"
                data-cpf="${escapeHtml(opts.cpf)}" data-url="${escapeHtml(opts.url)}"
                title="Consulta o nome pelo CPF (consulta paga, feita uma vez por CPF)">
                <i class="bi bi-eye me-1"></i>Revelar nome</button>`;
    }
    return '<span class="fw-semibold">Não informado</span>';
  }

  global.renderSeguradoNome = function (info, opts) {
    return `<div class="js-nome-segurado">${conteudo(info, opts)}</div>`;
  };

  document.addEventListener('click', async function (ev) {
    const btn = ev.target.closest('.js-revelar-nome');
    if (!btn) return;
    ev.preventDefault();
    const alvo = btn.closest('.js-nome-segurado');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Consultando…';
    try {
      const resp = await fetch(btn.dataset.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cpf: btn.dataset.cpf }),
      });
      const dados = await resp.json().catch(() => ({}));
      if (!resp.ok || !dados.ok) {
        throw new Error(dados.message || 'Não foi possível consultar o nome agora.');
      }
      alvo.innerHTML = conteudo(dados, {});
      // Outras linhas do mesmo CPF na página recebem o nome sem nova consulta.
      document.querySelectorAll(`.js-revelar-nome[data-cpf="${CSS.escape(btn.dataset.cpf)}"]`).forEach((outro) => {
        outro.closest('.js-nome-segurado').innerHTML = conteudo(dados, {});
      });
    } catch (e) {
      alvo.innerHTML = conteudo(null, { podeRevelar: true, cpf: btn.dataset.cpf, url: btn.dataset.url })
        + `<div class="small text-danger mt-1">${escapeHtml(e.message)}</div>`;
    }
  });
})(window);
