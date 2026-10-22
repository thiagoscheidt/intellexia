/* Biblioteca de IA (/prompts): abas, filtros, busca, cópia e modais.
 * Texto vindo do usuário entra sempre por textContent, nunca por innerHTML. */
(function () {
  'use strict';

  var cfg = window.PLB || {};
  var textos = JSON.parse(document.getElementById('plbTextos').textContent || '{}');
  var grade = document.getElementById('plbGrade');
  var cards = Array.prototype.slice.call(grade.querySelectorAll('.plb-card'));
  var secaoRec = grade.querySelector('[data-secao="rec"]');
  var secaoTodos = grade.querySelector('[data-secao="todos"]');
  var vazio = document.getElementById('plbVazio');
  var busca = document.getElementById('plbBusca');
  var ordem = document.getElementById('plbOrdem');
  var estado = { aba: cfg.abaInicial || 'meus', tipo: '', area: '', rec: '', usa: '' };

  var VAZIO = {
    meus: 'Você ainda não guardou nada. Em “+ Novo”, crie um prompt, agente ou skill — comece por aquele texto que você sempre cola no Claude.',
    escritorio: 'Ninguém compartilhou com o escritório ainda. Compartilhe um dos seus pelo menu ⋯ do card.',
    sistema: 'Nenhum comando pronto encontrado.',
    favoritos: 'Clique na estrela de um card para ele aparecer aqui.'
  };

  function semAcento(s) {
    return (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
      .replace(/[^a-z0-9\s]+/g, '');  // sem pontuação: "email" acha "E-mail"
  }
  cards.forEach(function (c) { c._busca = semAcento(c.dataset.busca); });

  function naAba(c) { return (' ' + c.dataset.abas + ' ').indexOf(' ' + estado.aba + ' ') >= 0; }
  function passaBusca(c, termos) { return termos.every(function (t) { return c._busca.indexOf(t) >= 0; }); }
  function passaFiltros(c, ignorar) {
    return ['tipo', 'area', 'rec', 'usa'].every(function (k) {
      return k === ignorar || !estado[k] || c.dataset[k] === estado[k];
    });
  }

  function comparar(a, b) {
    var o = ordem.value;
    if (o === 'az') return a.dataset.titulo.localeCompare(b.dataset.titulo, 'pt-BR');
    if (o === 'recentes') return (b.dataset.atualizado || '').localeCompare(a.dataset.atualizado || '');
    return (+b.dataset.usos) - (+a.dataset.usos) || a.dataset.titulo.localeCompare(b.dataset.titulo, 'pt-BR');
  }

  function contar(termos) {
    var base = cards.filter(function (c) { return naAba(c) && passaBusca(c, termos); });
    document.querySelectorAll('[data-conta-tipo]').forEach(function (el) {
      var v = el.dataset.contaTipo;
      el.textContent = base.filter(function (c) { return passaFiltros(c, 'tipo') && (!v || c.dataset.tipo === v); }).length;
    });
    document.querySelectorAll('[data-conta-area]').forEach(function (el) {
      var v = el.dataset.contaArea;
      el.textContent = base.filter(function (c) { return passaFiltros(c, 'area') && c.dataset.area === v; }).length;
    });
    var rec = document.querySelector('[data-conta-rec]');
    if (rec) rec.textContent = base.filter(function (c) { return passaFiltros(c, 'rec') && c.dataset.rec === '1'; }).length;
    var usa = document.querySelector('[data-conta-usa]');
    if (usa) usa.textContent = base.filter(function (c) { return passaFiltros(c, 'usa') && c.dataset.usa === '1'; }).length;
  }

  function aplicar() {
    var termos = semAcento(busca.value).split(/\s+/).filter(Boolean);
    var visiveis = cards.filter(function (c) {
      var ok = naAba(c) && passaBusca(c, termos) && passaFiltros(c);
      c.hidden = !ok;
      return ok;
    }).sort(comparar);

    var agrupar = estado.aba === 'escritorio' && !estado.rec;
    var recs = agrupar ? visiveis.filter(function (c) { return c.dataset.rec === '1'; }) : [];
    var resto = agrupar ? visiveis.filter(function (c) { return c.dataset.rec !== '1'; }) : visiveis;
    secaoRec.hidden = !recs.length;
    secaoTodos.hidden = !(recs.length && resto.length);
    grade.appendChild(secaoRec);
    recs.forEach(function (c) { grade.appendChild(c); });
    grade.appendChild(secaoTodos);
    resto.forEach(function (c) { grade.appendChild(c); });
    cards.filter(function (c) { return c.hidden; }).forEach(function (c) { grade.appendChild(c); });

    // Aviso "o conector tem N ferramentas": só na aba do IntellexIA.
    grade.querySelectorAll('[data-so-aba]').forEach(function (el) {
      el.hidden = el.dataset.soAba !== estado.aba;
      grade.insertBefore(el, grade.firstChild);
    });

    vazio.hidden = visiveis.length > 0;
    vazio.textContent = termos.length || estado.tipo || estado.area || estado.rec || estado.usa
      ? 'Nada encontrado com essa busca e esses filtros.' : (VAZIO[estado.aba] || '');
    grade.appendChild(vazio);

    document.querySelectorAll('[data-aba]').forEach(function (b) {
      b.classList.toggle('active', b.dataset.aba === estado.aba);
      b.setAttribute('aria-selected', b.dataset.aba === estado.aba ? 'true' : 'false');
    });
    document.querySelectorAll('[data-filtro]').forEach(function (b) {
      b.classList.toggle('active', estado[b.dataset.filtro] === b.dataset.valor && (b.dataset.valor || b.dataset.filtro === 'tipo'));
    });
    contar(termos);
  }

  document.querySelectorAll('[data-aba]').forEach(function (b) {
    b.addEventListener('click', function () {
      estado.aba = b.dataset.aba;
      try {
        var url = new URL(window.location.href);
        url.searchParams.set('aba', estado.aba);
        url.hash = '';
        window.history.replaceState(null, '', url);
      } catch (e) { /* navegador sem URL: só não guarda a aba */ }
      aplicar();
    });
  });
  document.querySelectorAll('[data-filtro]').forEach(function (b) {
    b.addEventListener('click', function () {
      var k = b.dataset.filtro;
      estado[k] = (estado[k] === b.dataset.valor) ? '' : b.dataset.valor;
      aplicar();
    });
  });
  busca.addEventListener('input', aplicar);
  ordem.addEventListener('change', aplicar);

  // Item vindo do editor (#item-12): abre a aba em que ele está.
  var alvo = window.location.hash && document.querySelector(window.location.hash.replace(/[^#\w-]/g, ''));
  if (alvo && alvo.classList.contains('plb-card') && !naAba(alvo)) {
    estado.aba = alvo.dataset.abas.split(' ')[0] || estado.aba;
  }
  aplicar();
  if (alvo && alvo.scrollIntoView) alvo.scrollIntoView({ block: 'center' });

  // ── aviso ──────────────────────────────────────────────────────────────
  var aviso = document.getElementById('plbAviso');
  var avisoTimer = null;
  function avisar(texto, tipo) {
    aviso.innerHTML = '';
    var div = document.createElement('div');
    div.className = 'alert alert-' + (tipo || 'success') + ' shadow mb-0 py-2';
    div.textContent = texto;
    aviso.appendChild(div);
    clearTimeout(avisoTimer);
    avisoTimer = setTimeout(function () { aviso.innerHTML = ''; }, 4500);
  }

  // ── copiar / abrir no Claude ───────────────────────────────────────────
  function copiar(texto) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(texto);
    }
    return new Promise(function (ok, falha) {
      var t = document.createElement('textarea');
      t.value = texto;
      t.setAttribute('readonly', '');
      t.style.position = 'fixed';
      t.style.opacity = '0';
      document.body.appendChild(t);
      t.select();
      try { document.execCommand('copy') ? ok() : falha(); } catch (e) { falha(e); } finally { t.remove(); }
    });
  }

  function registrarUso(id) {
    var dados = textos[id];
    if (!dados || dados.sistema) return;
    fetch(cfg.urls.uso.replace('/0/', '/' + id + '/'), { method: 'POST', headers: { 'X-Requested-With': 'fetch' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j) return;
        var card = document.getElementById('item-' + id);
        if (!card) return;
        card.dataset.usos = j.usos;
        var rot = card.querySelector('[data-usos-rotulo]');
        if (rot) rot.textContent = j.usos + (j.usos === 1 ? ' uso' : ' usos');
      })
      .catch(function () { /* contagem é detalhe: não atrapalha a cópia */ });
  }

  function copiarTexto(id, texto) {
    return copiar(texto).then(function () {
      registrarUso(id);
      avisar('Copiado. É só colar no Claude.');
    }, function () {
      avisar('Não consegui copiar automaticamente. Selecione o texto e copie com Ctrl+C.', 'warning');
    });
  }

  function abrirClaude(id, texto) {
    var q = encodeURIComponent(texto);
    var url = 'https://claude.ai/new' + (q.length <= 12000 ? '?q=' + q : '');
    // Abre já, no clique (pop-up bloqueado se esperar a cópia); a cópia é a garantia.
    window.open(url, '_blank', 'noopener');
    copiar(texto).then(function () {
      registrarUso(id);
      avisar('Texto copiado. Se não aparecer no Claude, cole com Ctrl+V.');
    }, function () {
      avisar('Abri o Claude, mas não consegui copiar o texto. Use o botão Copiar.', 'warning');
    });
  }

  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-copiar]');
    if (b) { var id = b.dataset.copiar; copiarTexto(id, textos[id].texto); return; }
    b = e.target.closest('[data-abrir-claude]');
    if (b) {
      var idc = b.dataset.abrirClaude;
      if (textos[idc].campos.length) { abrirPreencher(idc); return; }
      abrirClaude(idc, textos[idc].texto);
      return;
    }
    b = e.target.closest('[data-preencher]');
    if (b) { abrirPreencher(b.dataset.preencher); return; }
    b = e.target.closest('[data-favorito]');
    if (b) { alternarFavorito(b); return; }
    b = e.target.closest('[data-versoes]');
    if (b) { abrirVersoes(b.dataset.versoes); return; }
    b = e.target.closest('[data-acao]');
    if (b) { enviarAcao(b); }
  });

  // ── preencher campos ───────────────────────────────────────────────────
  var modalPreencher = document.getElementById('plbPreencher');
  var camposBox = document.getElementById('plbCampos');
  var previa = document.getElementById('plbPrevia');
  var preenchendo = null;

  function textoPreenchido() {
    var d = textos[preenchendo];
    var valores = {};
    camposBox.querySelectorAll('input').forEach(function (i) { valores[i.name] = i.value.trim(); });
    return d.texto.replace(/\{\{\s*([\p{L}_][\p{L}\p{N}_]{0,59})\s*\}\}/gu, function (m, nome) {
      return valores[nome] ? valores[nome] : m;
    });
  }
  function atualizarPrevia() { previa.textContent = textoPreenchido(); }

  function rotulo(nome) {
    var s = nome.replace(/_/g, ' ');
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function abrirPreencher(id) {
    preenchendo = id;
    var d = textos[id];
    document.getElementById('plbPreencherTitulo').textContent = d.titulo;
    camposBox.innerHTML = '';
    d.campos.forEach(function (nome, n) {
      var col = document.createElement('div');
      col.className = 'col-md-6';
      var lab = document.createElement('label');
      lab.className = 'form-label small mb-1';
      lab.htmlFor = 'plbCampo' + n;
      lab.textContent = rotulo(nome);
      var inp = document.createElement('input');
      inp.className = 'form-control';
      inp.id = 'plbCampo' + n;
      inp.name = nome;
      inp.addEventListener('input', atualizarPrevia);
      col.appendChild(lab);
      col.appendChild(inp);
      camposBox.appendChild(col);
    });
    atualizarPrevia();
    var m = bootstrap.Modal.getOrCreateInstance(modalPreencher);
    m.show();
    modalPreencher.addEventListener('shown.bs.modal', function foco() {
      // setTimeout: o AdminLTE foca o X da janela depois deste ouvinte.
      setTimeout(function () {
        var p = camposBox.querySelector('input');
        if (p) p.focus();
      }, 0);
      modalPreencher.removeEventListener('shown.bs.modal', foco);
    });
  }
  document.getElementById('plbPreencherCopiar').addEventListener('click', function () {
    copiarTexto(preenchendo, textoPreenchido());
  });
  document.getElementById('plbPreencherClaude').addEventListener('click', function () {
    abrirClaude(preenchendo, textoPreenchido());
  });

  // ── favoritos ──────────────────────────────────────────────────────────
  function alternarFavorito(b) {
    var id = b.dataset.favorito;
    var novo = !b.classList.contains('on');
    fetch(cfg.urls.favorito.replace('/0/', '/' + id + '/'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ favorito: novo })
    }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).then(function (j) {
      b.classList.toggle('on', j.favorito);
      b.setAttribute('aria-pressed', j.favorito ? 'true' : 'false');
      b.title = j.favorito ? 'Tirar dos favoritos' : 'Favoritar';
      b.querySelector('i').className = 'bi ' + (j.favorito ? 'bi-star-fill' : 'bi-star');
      var card = document.getElementById('item-' + id);
      var abas = card.dataset.abas.split(' ').filter(function (a) { return a && a !== 'favoritos'; });
      if (j.favorito) abas.push('favoritos');
      card.dataset.abas = abas.join(' ');
      var total = document.querySelector('[data-favoritos-total]');
      if (total) total.textContent = cards.filter(function (c) { return / favoritos( |$)/.test(' ' + c.dataset.abas); }).length;
      if (estado.aba === 'favoritos') aplicar();
    }).catch(function () { avisar('Não consegui salvar o favorito. Tente de novo.', 'danger'); });
  }

  // ── ações por formulário (duplicar, compartilhar, arquivar...) ─────────
  var form = document.getElementById('plbForm');
  function enviarAcao(b) {
    if (b.dataset.confirmar && !window.confirm(b.dataset.confirmar)) return;
    form.action = b.dataset.acao;
    form.elements.visibilidade.value = b.dataset.visibilidade || '';
    form.elements.valor.value = b.dataset.valor || '';
    form.elements.voltar.value = window.location.pathname + '?aba=' + encodeURIComponent(estado.aba);
    form.submit();
  }

  // ── versões ────────────────────────────────────────────────────────────
  var modalVersoes = document.getElementById('plbVersoes');
  var corpoVersoes = document.getElementById('plbVersoesCorpo');
  function el(tag, classe, texto) {
    var x = document.createElement(tag);
    if (classe) x.className = classe;
    if (texto !== undefined) x.textContent = texto;
    return x;
  }
  function abrirVersoes(id) {
    corpoVersoes.innerHTML = '';
    corpoVersoes.appendChild(el('div', 'text-body-secondary', 'Carregando…'));
    bootstrap.Modal.getOrCreateInstance(modalVersoes).show();
    fetch(cfg.urls.versoes.replace('/0/', '/' + id + '/'))
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (j) {
        corpoVersoes.innerHTML = '';
        document.getElementById('plbVersoesTitulo').textContent = 'Versões de “' + textos[id].titulo + '”';
        var lista = el('div', 'accordion');
        lista.id = 'plbVersoesLista';
        j.versoes.forEach(function (v, n) {
          var item = el('div', 'accordion-item');
          var h = el('h2', 'accordion-header');
          var bt = el('button', 'accordion-button' + (n ? ' collapsed' : ''));
          bt.type = 'button';
          bt.setAttribute('data-bs-toggle', 'collapse');
          bt.setAttribute('data-bs-target', '#plbV' + v.versao);
          var quando = new Date(v.em).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
          bt.textContent = 'Versão ' + v.versao + (v.versao === j.atual ? ' (atual)' : '') + ' — ' + v.autor + ', ' + quando;
          h.appendChild(bt);
          var corpo = el('div', 'accordion-collapse collapse' + (n ? '' : ' show'));
          corpo.id = 'plbV' + v.versao;
          corpo.setAttribute('data-bs-parent', '#plbVersoesLista');
          var dentro = el('div', 'accordion-body');
          dentro.appendChild(el('div', 'fw-semibold mb-1', v.titulo));
          if (v.descricao) dentro.appendChild(el('div', 'small text-body-secondary mb-2', v.descricao));
          dentro.appendChild(el('pre', 'plb-pre', v.corpo));
          if (v.anexos.length) dentro.appendChild(el('div', 'small text-body-secondary mt-2', 'Anexos: ' + v.anexos.join(', ')));
          if (j.pode_restaurar && v.versao !== j.atual) {
            var rb = el('button', 'btn btn-sm btn-outline-primary mt-2', 'Restaurar esta versão');
            rb.type = 'button';
            rb.dataset.acao = cfg.urls.restaurar.replace('/0/', '/' + id + '/').replace('999999', v.versao);
            rb.dataset.confirmar = 'Restaurar a versão ' + v.versao + '? Ela vira uma versão nova; nada se perde.';
            dentro.appendChild(rb);
          }
          corpo.appendChild(dentro);
          item.appendChild(h);
          item.appendChild(corpo);
          lista.appendChild(item);
        });
        corpoVersoes.appendChild(lista);
      })
      .catch(function () {
        corpoVersoes.innerHTML = '';
        corpoVersoes.appendChild(el('div', 'text-danger', 'Não consegui carregar as versões.'));
      });
  }
})();
