/* Janela rápida da Biblioteca de IA (header + Ctrl+K): busca, ↑ ↓ Enter, copiar
 * e preencher campos sem sair da tela. Itens lidos de /prompts/rapido.json na
 * primeira abertura. Texto do usuário sempre por textContent. */
(function () {
  'use strict';

  var modal = document.getElementById('bibliotecaRapida');
  if (!modal) return;
  var URL_ITENS = modal.dataset.urlItens;
  var URL_USO = modal.dataset.urlUso;            // com /0/ no lugar do id
  var busca = document.getElementById('brBusca');
  var lista = document.getElementById('brLista');
  var estado = document.getElementById('brEstado');
  var aviso = document.getElementById('brAviso');
  var itens = null;
  var visiveis = [];
  var ativo = 0;
  var preenchendo = null;
  var CAMPO = /\{\{\s*([\p{L}_][\p{L}\p{N}_]{0,59})\s*\}\}/gu;

  function semAcento(t) { return (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
      .replace(/[^a-z0-9\s]+/g, '');  // sem pontuação: "email" acha "E-mail"
  }
  function el(tag, classe, texto) {
    var x = document.createElement(tag);
    if (classe) x.className = classe;
    if (texto !== undefined && texto !== null) x.textContent = texto;
    return x;
  }

  function vista(nome) {
    modal.querySelectorAll('[data-br-vista]').forEach(function (v) { v.hidden = v.dataset.brVista !== nome; });
  }

  function avisar(t, erro) {
    aviso.textContent = t;
    aviso.className = 'small ' + (erro ? 'text-danger' : 'text-success');
    clearTimeout(avisar._t);
    avisar._t = setTimeout(function () { aviso.textContent = ''; }, 4000);
  }

  // ── carregar (uma vez por página) ─────────────────────────────────────
  function carregar() {
    if (itens) { desenhar(); return; }
    estado.hidden = false;
    estado.textContent = 'Carregando…';
    fetch(URL_ITENS, { headers: { 'Accept': 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (j) {
        itens = j.itens.map(function (i) {
          i._busca = semAcento([i.titulo, i.descricao, i.comando, i.texto, i.area_rotulo, i.tipo_rotulo].join(' '));
          return i;
        });
        desenhar();
      })
      .catch(function () { estado.textContent = 'Não consegui carregar a biblioteca. Tente de novo.'; });
  }

  // ── lista ──────────────────────────────────────────────────────────────
  function linha(i) {
    var b = el('button', 'br-item');
    b.type = 'button';
    b.setAttribute('role', 'option');
    var ic = el('span', 'br-icone');
    ic.appendChild(el('i', 'bi ' + i.tipo_icone));
    b.appendChild(ic);
    var tx = el('span', 'br-texto');
    var t = el('span', 'br-titulo d-block');
    if (i.favorito) { var s = el('i', 'bi bi-star-fill text-warning me-1'); t.appendChild(s); }
    t.appendChild(document.createTextNode(i.titulo));
    tx.appendChild(t);
    var sub = el('span', 'br-sub d-block');
    sub.appendChild(document.createTextNode(i.tipo_rotulo + ' · ' + (i.sistema ? 'IntellexIA' : (i.visibilidade === 'escritorio' ? 'Escritório' : 'Só eu')) + ' · '));
    sub.appendChild(el('span', 'br-cmd', '/' + i.comando));
    tx.appendChild(sub);
    b.appendChild(tx);
    b.appendChild(el('span', 'br-acao', i.campos.length ? 'Preencher' : 'Copiar'));
    b.addEventListener('click', function () { usar(i); });
    b.addEventListener('mousemove', function () { marcar(visiveis.indexOf(i)); });
    return b;
  }

  function ordemPadrao(a, b) { return (b.usos - a.usos) || a.titulo.localeCompare(b.titulo, 'pt-BR'); }

  function desenhar() {
    lista.innerHTML = '';
    estado.hidden = true;
    var termos = semAcento(busca.value).split(/\s+/).filter(Boolean);
    var grupos;
    if (termos.length) {
      var achados = itens.filter(function (i) { return termos.every(function (t) { return i._busca.indexOf(t) >= 0; }); })
        .sort(function (a, b) { return (b.favorito - a.favorito) || (b.recomendado - a.recomendado) || ordemPadrao(a, b); })
        .slice(0, 50);
      grupos = [['Resultados', achados]];
    } else {
      var favs = itens.filter(function (i) { return i.favorito; }).sort(ordemPadrao);
      var recs = itens.filter(function (i) { return i.recomendado && !i.favorito; }).sort(ordemPadrao);
      var usados = itens.filter(function (i) { return !i.favorito && !i.recomendado && !i.sistema; }).sort(ordemPadrao).slice(0, 8);
      grupos = [['Favoritos', favs], ['Recomendados pelo escritório', recs], ['Mais usados', usados]];
      if (!favs.length && !recs.length && !usados.length) {
        grupos = [['Do IntellexIA', itens.filter(function (i) { return i.sistema; }).slice(0, 8)]];
      }
    }
    visiveis = [];
    grupos.forEach(function (g) {
      if (!g[1].length) return;
      lista.appendChild(el('div', 'br-secao', g[0]));
      g[1].forEach(function (i) { visiveis.push(i); lista.appendChild(linha(i)); });
    });
    if (!visiveis.length) {
      estado.hidden = false;
      estado.textContent = termos.length ? 'Nada encontrado com essa busca.' : 'A biblioteca está vazia. Use “Novo” para guardar o primeiro.';
    }
    marcar(0);
  }

  function marcar(n) {
    var botoes = lista.querySelectorAll('.br-item');
    if (!botoes.length) return;
    ativo = Math.max(0, Math.min(n, botoes.length - 1));
    botoes.forEach(function (b, k) {
      b.classList.toggle('ativo', k === ativo);
      b.setAttribute('aria-selected', k === ativo ? 'true' : 'false');
    });
  }

  busca.addEventListener('input', function () { if (itens) desenhar(); });
  busca.addEventListener('keydown', function (e) {
    var botoes = lista.querySelectorAll('.br-item');
    if (e.key === 'ArrowDown') { e.preventDefault(); marcar(ativo + 1); botoes[ativo] && botoes[ativo].scrollIntoView({ block: 'nearest' }); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); marcar(ativo - 1); botoes[ativo] && botoes[ativo].scrollIntoView({ block: 'nearest' }); }
    else if (e.key === 'Enter') { e.preventDefault(); if (visiveis[ativo]) usar(visiveis[ativo]); }
  });

  // ── usar: copiar ou preencher ─────────────────────────────────────────
  function copiar(texto) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(texto);
    return new Promise(function (ok, falha) {
      var t = el('textarea'); t.value = texto; t.style.position = 'fixed'; t.style.opacity = '0';
      document.body.appendChild(t); t.select();
      try { document.execCommand('copy') ? ok() : falha(); } catch (e) { falha(e); } finally { t.remove(); }
    });
  }
  function contarUso(i) {
    if (i.sistema) return;
    fetch(URL_USO.replace('/0/', '/' + i.id + '/'), { method: 'POST' }).catch(function () {});
    i.usos += 1;
  }
  function copiarTexto(i, texto) {
    copiar(texto).then(function () { contarUso(i); avisar('Copiado: “' + i.titulo + '”. É só colar no Claude.'); },
      function () { avisar('Não consegui copiar. Abra o item na biblioteca e copie de lá.', true); });
  }
  function usar(i) {
    if (i.campos.length) { abrirPreencher(i); return; }
    copiarTexto(i, i.texto);
  }

  var campos = document.getElementById('brCampos');
  var previa = document.getElementById('brPrevia');
  function preenchido() {
    var v = {};
    campos.querySelectorAll('input').forEach(function (x) { v[x.name] = x.value.trim(); });
    return preenchendo.texto.replace(CAMPO, function (m, nome) { return v[nome] ? v[nome] : m; });
  }
  function abrirPreencher(i) {
    preenchendo = i;
    document.getElementById('brPreencherTitulo').textContent = i.titulo;
    campos.innerHTML = '';
    i.campos.forEach(function (nome, n) {
      var col = el('div', 'col-md-6');
      var lab = el('label', 'form-label small mb-1', nome.replace(/_/g, ' ').replace(/^./, function (c) { return c.toUpperCase(); }));
      lab.htmlFor = 'brCampo' + n;
      var inp = el('input', 'form-control');
      inp.id = 'brCampo' + n; inp.name = nome;
      inp.addEventListener('input', function () { previa.textContent = preenchido(); });
      inp.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); copiarTexto(preenchendo, preenchido()); }
      });
      col.appendChild(lab); col.appendChild(inp); campos.appendChild(col);
    });
    previa.textContent = preenchido();
    vista('preencher');
    var p = campos.querySelector('input');
    if (p) p.focus();
  }
  document.getElementById('brVoltar').addEventListener('click', function () { vista('lista'); busca.focus(); });
  document.getElementById('brCopiar').addEventListener('click', function () { copiarTexto(preenchendo, preenchido()); });
  document.getElementById('brClaude').addEventListener('click', function () {
    var t = preenchido();
    var q = encodeURIComponent(t);
    window.open('https://claude.ai/new' + (q.length <= 12000 ? '?q=' + q : ''), '_blank', 'noopener');
    copiar(t).then(function () { contarUso(preenchendo); avisar('Texto copiado. Se não aparecer no Claude, cole com Ctrl+V.'); });
  });

  // ── abrir ──────────────────────────────────────────────────────────────
  modal.addEventListener('show.bs.modal', function () { vista('lista'); busca.value = ''; carregar(); });
  // O AdminLTE põe o foco no 1º elemento da janela (o X) num ouvinte do document,
  // que roda depois deste: o setTimeout deixa a busca com o cursor.
  modal.addEventListener('shown.bs.modal', function () { setTimeout(function () { busca.focus(); }, 0); });

  // Ctrl+K (Cmd+K no Mac) abre e fecha de qualquer tela.
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      bootstrap.Modal.getOrCreateInstance(modal).toggle();
    }
  });
})();
