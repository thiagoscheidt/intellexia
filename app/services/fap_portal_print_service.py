"""
Print da Consulta do FAP: abre a tela do portal com a sessão da instalação e guarda a imagem.

Fonte única da ferramenta ``print_consulta_fap`` (MCP), da rota
``POST /api/v1/fap/consulta/print`` e da imagem em ``/fap-panel/print-portal/<nome>``.

Quem navega é o ``fap_portal_navegador``, num **subprocesso** com tempo-limite
(o Playwright síncrono não roda no loop asyncio do MCP, e um Chromium travado
morre com o processo). Aqui ficam as regras:

- **Só o escritório do ``FAP_SYNC_LAW_FIRM_ID``**: a sessão do portal
  (``FAP_AUTH_JSON``) é da instalação e enxerga as empresas das procurações
  dela — outro escritório veria dados que não são seus.
- **Só CNPJ da base do escritório** (estabelecimento do cálculo FAP ou raiz de
  empresa do Painel FAP), com dígito verificador válido: sem isso a ferramenta
  viraria consulta avulsa ao portal.
- **Um navegador por vez** na máquina (trava de arquivo entre o MCP e os
  workers do app): o portal é um só e a sessão também.
- O print sai **cru**, como o escritório faz hoje. Quem capturou, quando e de
  qual cálculo vai na resposta e no ``.json`` ao lado da imagem.
- As imagens ficam em ``instance/prints_fap/<escritório>/`` (fora do git; têm
  dados de segurados) e são apagadas depois de ``RETENCAO_DIAS``.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parents[2]
DIR_PRINTS = RAIZ_PROJETO / 'instance' / 'prints_fap'
ARQUIVO_TRAVA = DIR_PRINTS / '.navegador.lock'
RETENCAO_DIAS = 7
ESPERA_TRAVA_S = 120
TEMPO_LIMITE_S = 180

TELAS = {
    'calculo': 'Tela da Consulta do FAP (cálculo do estabelecimento)',
    'B91': 'Benefícios B91 do cálculo',
    'B92': 'Benefícios B92 do cálculo',
    'B93': 'Benefícios B93 do cálculo',
    'B94': 'Benefícios B94 do cálculo',
    'CAT': 'CATs do cálculo',
    'beneficios_pagos': 'Valor total de benefícios pagos (todos os benefícios)',
    'massa_salarial': 'Detalhamento da massa salarial',
    'vinculos': 'Detalhamento do número médio de vínculos',
}
TELAS_COM_NUMERO = {'B91', 'B92', 'B93', 'B94', 'CAT', 'beneficios_pagos'}
CALCULOS = ('atual', 'original')
_NOME_IMAGEM = re.compile(r'^[0-9a-f]{32}_[12]\.png$')

# código do navegador → status HTTP da API
STATUS_DO_CODIGO = {
    'sessao_expirada': 503,
    'portal_indisponivel': 503,
    'erro_navegacao': 502,
    'ocupado': 503,
    'vigencia_inexistente': 404,
    'empresa_fora_do_portal': 404,
    'estabelecimento_fora_do_portal': 404,
    'sem_calculo': 404,
    'sem_calculo_original': 404,
    'sem_itens': 404,
    'numero_nao_encontrado': 404,
}


class PrintFapIndisponivel(Exception):
    """Pedido recusado ou captura que não deu certo. ``status_http`` vai para a API."""

    def __init__(self, mensagem: str, status_http: int = 400, codigo: str = 'pedido_invalido'):
        super().__init__(mensagem)
        self.status_http = status_http
        self.codigo = codigo


@dataclass
class PrintFap:
    id: str
    cnpj: str
    vigencia: int
    tela: str
    numero: str | None
    calculo: str
    empresa: str
    fap: str
    calculo_rotulo: str
    linhas: int | None
    linhas_omitidas: int
    capturado_em: datetime          # UTC
    partes: list[dict]              # {'nome', 'descricao'}
    sessao_parcial: bool


# ── Regras do pedido ─────────────────────────────────────────────────────────

def escritorio_da_sessao() -> int | None:
    try:
        return int(os.environ.get('FAP_SYNC_LAW_FIRM_ID') or 0) or None
    except ValueError:
        return None


def _so_digitos(valor) -> str:
    return re.sub(r'\D', '', str(valor or ''))


def cnpj_da_base(law_firm_id: int, cnpj: str) -> bool:
    """O estabelecimento está no cálculo FAP do escritório, ou a raiz é de uma empresa do Painel FAP."""
    from app.models import FapCalculoEstabelecimento, FapCompany

    if FapCalculoEstabelecimento.query.filter_by(law_firm_id=law_firm_id, cnpj=cnpj).first():
        return True
    raiz = cnpj[:8]
    for (bruto,) in FapCompany.query.with_entities(FapCompany.cnpj).filter_by(law_firm_id=law_firm_id):
        d = _so_digitos(bruto)
        # o portal manda CNPJ como número: a raiz pode ter chegado sem os zeros da frente
        if (d.zfill(14)[:8] if len(d) > 8 else d.zfill(8)) == raiz:
            return True
    return False


def validar(law_firm_id: int, cnpj, vigencia, tela, numero=None, calculo=None) -> dict:
    """Pedido normalizado, ou ``PrintFapIndisponivel``."""
    from app.services.dou_alert_service import cnpj_valido

    if escritorio_da_sessao() != law_firm_id:
        raise PrintFapIndisponivel(
            'O print do portal FAP usa a sessão do portal desta instalação, que é de outro escritório.', 403,
            'outro_escritorio')
    c = _so_digitos(cnpj)
    if 8 < len(c) < 14:      # CNPJ que passou por número perdeu os zeros da frente
        c = c.zfill(14)
    if not cnpj_valido(c):
        raise PrintFapIndisponivel('Informe o CNPJ completo do estabelecimento (14 dígitos, com dígito '
                                   'verificador válido).')
    try:
        ano = int(vigencia)
    except (TypeError, ValueError):
        raise PrintFapIndisponivel('Informe a vigência (ano), ex.: 2026.')
    if not 2010 <= ano <= datetime.now().year + 2:
        raise PrintFapIndisponivel(f'Vigência {ano} fora do intervalo do FAP.')
    tela = (tela or 'calculo').strip()
    tela = {k.lower(): k for k in TELAS}.get(tela.lower(), tela)
    if tela not in TELAS:
        raise PrintFapIndisponivel(f'Tela "{tela}" desconhecida. Use: {", ".join(TELAS)}.')
    n = _so_digitos(numero) or None
    if numero and not n:
        raise PrintFapIndisponivel('O número (NB ou CAT) precisa ter dígitos.')
    if n and tela not in TELAS_COM_NUMERO:
        raise PrintFapIndisponivel(f'O filtro por número só vale para {", ".join(sorted(TELAS_COM_NUMERO))}.')
    calc = (calculo or 'atual').strip().lower()
    if calc not in CALCULOS:
        raise PrintFapIndisponivel('calculo deve ser "atual" ou "original".')
    if not cnpj_da_base(law_firm_id, c):
        raise PrintFapIndisponivel(
            f'O CNPJ {c} não está no Painel FAP nem no cálculo FAP do escritório.', 404, 'fora_da_base')
    return {'cnpj': c, 'vigencia': ano, 'tela': tela, 'numero': n, 'calculo': calc}


# ── Execução ─────────────────────────────────────────────────────────────────

def _rodar_navegador(pedido: dict, pasta: Path) -> dict:
    """Roda o navegador num processo à parte e lê a linha de JSON da resposta."""
    try:
        r = subprocess.run(
            [sys.executable, '-m', 'app.services.fap_portal_navegador',
             '--pedido', json.dumps(pedido), '--saida', str(pasta)],
            cwd=str(RAIZ_PROJETO), capture_output=True, text=True, timeout=TEMPO_LIMITE_S,
        )
    except subprocess.TimeoutExpired:
        return {'ok': False, 'codigo': 'erro_navegacao',
                'mensagem': f'O portal não terminou em {TEMPO_LIMITE_S} s.'}
    linhas = [l for l in (r.stdout or '').splitlines() if l.strip().startswith('{')]
    if not linhas:
        erro = (r.stderr or '').strip().splitlines()[-1:] or ['sem resposta']
        return {'ok': False, 'codigo': 'erro_navegacao', 'mensagem': erro[0][:300]}
    return json.loads(linhas[-1])


class _Trava:
    """Trava de arquivo: um Chromium por vez na máquina, entre processos."""

    def __enter__(self):
        DIR_PRINTS.mkdir(parents=True, exist_ok=True)
        self._f = open(ARQUIVO_TRAVA, 'w')
        limite = time.monotonic() + ESPERA_TRAVA_S
        while True:
            try:
                fcntl.flock(self._f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() > limite:
                    self._f.close()
                    raise PrintFapIndisponivel(
                        'Outro print do portal FAP está em andamento há mais de 2 minutos. Tente de novo '
                        'em instantes.', 503, 'ocupado')
                time.sleep(1)

    def __exit__(self, *exc):
        fcntl.flock(self._f, fcntl.LOCK_UN)
        self._f.close()


def _pasta(law_firm_id: int) -> Path:
    return DIR_PRINTS / str(int(law_firm_id))


def _podar(pasta: Path) -> None:
    corte = time.time() - RETENCAO_DIAS * 86400
    for arq in pasta.glob('*'):
        try:
            if arq.is_file() and arq.stat().st_mtime < corte:
                arq.unlink()
        except OSError:
            pass


def capturar(law_firm_id: int, user_id: int | None, cnpj, vigencia, tela='calculo', numero=None,
             calculo='atual', *, navegador=None) -> PrintFap:
    """Valida, abre o portal e guarda as imagens. ``navegador`` substitui o subprocesso (testes)."""
    pedido = validar(law_firm_id, cnpj, vigencia, tela, numero, calculo)
    navegador = navegador or _rodar_navegador
    destino = _pasta(law_firm_id)
    destino.mkdir(parents=True, exist_ok=True)
    _podar(destino)

    with _Trava(), tempfile.TemporaryDirectory(prefix='print_fap_', dir=str(DIR_PRINTS)) as tmp:
        resposta = navegador(pedido, Path(tmp))
        if not resposta.get('ok'):
            codigo = resposta.get('codigo') or 'erro_navegacao'
            raise PrintFapIndisponivel(resposta.get('mensagem') or 'O portal não devolveu a tela.',
                                       STATUS_DO_CODIGO.get(codigo, 502), codigo)
        ident = uuid.uuid4().hex
        partes = []
        for i, parte in enumerate(resposta.get('partes') or [], start=1):
            origem = Path(parte['arquivo'])
            if i > 2 or not origem.is_file() or origem.resolve().parent != Path(tmp).resolve():
                continue
            nome = f'{ident}_{i}.png'
            shutil.move(str(origem), destino / nome)
            partes.append({'nome': nome, 'descricao': parte.get('descricao') or ''})
        if not partes:
            raise PrintFapIndisponivel('O portal abriu, mas a imagem não foi gravada.', 502, 'erro_navegacao')

    agora = datetime.now(timezone.utc)
    p = PrintFap(
        id=ident, cnpj=pedido['cnpj'], vigencia=pedido['vigencia'], tela=pedido['tela'],
        numero=pedido['numero'], calculo=pedido['calculo'], empresa=resposta.get('empresa') or '',
        fap=resposta.get('fap') or '', calculo_rotulo=resposta.get('calculo') or '',
        linhas=resposta.get('linhas'), linhas_omitidas=int(resposta.get('linhas_omitidas') or 0),
        capturado_em=agora, partes=partes, sessao_parcial=bool(resposta.get('sessao_parcial')),
    )
    meta = {**p.__dict__, 'capturado_em': agora.isoformat(), 'user_id': user_id}
    (destino / f'{ident}.json').write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
    return p


def arquivo_da_imagem(law_firm_id: int, nome: str) -> Path | None:
    """A imagem, se o nome for de print e existir na pasta deste escritório."""
    if not _NOME_IMAGEM.match(nome or ''):
        return None
    caminho = _pasta(law_firm_id) / nome
    return caminho if caminho.is_file() else None


def expira_em(p: PrintFap) -> datetime:
    return p.capturado_em + timedelta(days=RETENCAO_DIAS)
