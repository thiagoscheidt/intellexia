"""
Importação do lote de Markdown (petições protocoladas + decisões).

Cada verificação tranca algo do lote real: CSV saído do Excel (cp1252,
tabulação, "07/07" virado "07/jul"), .md renomeado em relação ao PDF da
planilha, linha não convertida, arquivo fora do índice — e a regra de que o
arquivo entra como veio, sem tocar a pasta de origem.

Roda contra SQLite descartável, sem IA nem índice de verdade.

Executar:
    uv run python tests/test_importar_lote_md.py
"""

import hashlib
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_lote_md.db')
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_FILE}'

from app.models import db  # noqa: E402

app.extensions.pop('sqlalchemy', None)
try:
    db._app_engines.pop(app, None)
except Exception:
    pass
db.init_app(app)

from app.models import (  # noqa: E402
    ImpugnacaoReferenceModel, JurisprudenceDecision, JurisprudenceUpload, KnowledgeBase, LawFirm, User,
)
from app.services import jurisprudence_index_service as indice  # noqa: E402
from app.services import jurisprudence_upload_service as envios  # noqa: E402
from app.services import lote_md_import_service as lote  # noqa: E402

# Tudo numa pasta própria — nunca em uploads/, que em dev tem dado real.
TMP = Path(tempfile.mkdtemp(prefix='lote_md_teste_'))
envios.UPLOAD_BASE_DIR = str(TMP / 'uploads' / 'jurisprudence')
PASTA = TMP / 'lote'

FALHAS = []


def check(rotulo, condicao, extra=''):
    print(f"  [{'OK ' if condicao else 'FALHA'}] {rotulo}{(' — ' + str(extra)) if extra else ''}")
    if not condicao:
        FALHAS.append(rotulo)


# Acórdão com o OCR repetido, como o da Santos Brasil: entra assim mesmo.
MD_ACORDAO = ('# ACÓRDÃO\n\n*Convertido de `x.pdf`*\n\nEMENTA: TRIBUTÁRIO. FAP. TRAJETO.\n\n'
              'EMENTA: TRIBUTÁRIO. FAP. TRAJETO.\n\nVoto do relator. <mark>destaque</mark>\n')
MD_SENTENCA = '# SENTENÇA\n\nJulgo procedente o pedido de exclusão do benefício B91 de trajeto.\n'
MD_EMBARGOS = '# SENTENÇA ED\n\nRejeito os embargos.\n'
MD_NOVA = '# SENTENÇA\n\nDecisão que não está na planilha.\n'
MD_IMPUG = ('# 2026-10-09 - CNH - IMPUGNAÇÃO\n\n**PDF no Drive:** https://drive.google.com/file/d/1NxLdsJ597El3ZqAdGjyh/view\n\n'
            '---\n\n## EXCELENTÍSSIMO JUIZ FEDERAL DA 19ª VARA DE BELO HORIZONTE\n\n'
            'Processo nº 6074477-21.2026.4.06.3800\n\nCitando o precedente 5003321-10.2023.4.04.7000.\n\n'
            '## 1. Da insuficiência da contestação\n\nTexto da peça.\n')
MD_APELACAO = '# APELAÇÃO\n\nRazões recursais.\n'

NOME_ACORDAO = '2026-06-26 - ACÓRDÃO - SANTOS BRASIL - 5001181-56.2023.4.03.6100.md'
NOME_SENTENCA = '2019-05-20 - SENTENÇA - EMBRACON - 5007301-28.2019.4.04.7200.md'
NOME_EMBARGOS = '2019-08-21 - SENTENÇAED - EMBRACON - 5007301-28.2019.4.04.7200.md'
NOME_DERESP = '2026-02-15 - DERESP - KHRONOS - 5006656-95.2022.4.04.7200.md'
NOME_RESP = '2026-02-16 - DERESP - LOJAS - 5000003-11.2021.4.04.7000.md'
NOME_RE = '2026-02-16 - DERE - LOJAS - 5000003-11.2021.4.04.7000.md'
NOME_COPIA = 'Sentença - EMBRACON.md'
NOME_NOVA = '2020-01-10 - SENTENÇA - NOVA - 5000001-11.2020.4.04.7000.md'
NOME_IMPUG = '2026-10-09 - CNH INDUSTRIAL BRASIL LTDA. (2016-2024) - IMPUGNAÇÃO À CONTESTAÇÃO.md'
NOME_APELACAO = '2026-10-09 - COAMO AGROINDUSTRIAL COOPERATIVA (2023) - APELAÇÃO.md'


def extraido(nome, codigo):
    """O nome como o `unzip` do servidor grava: ignora a marca UTF-8 do zip e
    lê pela página de código do DOS ("SENTENÇA" → "SENTEN├ЗA")."""
    return nome.encode('utf-8').decode(codigo) if codigo else nome


def montar_lote():
    dec = PASTA / 'decisoes'
    pet = PASTA / 'peticoes_protocoladas'
    dec.mkdir(parents=True)
    pet.mkdir(parents=True)
    for nome, texto in [(NOME_ACORDAO, MD_ACORDAO), (NOME_SENTENCA, MD_SENTENCA),
                        (NOME_EMBARGOS, MD_EMBARGOS), (NOME_NOVA, MD_NOVA), (NOME_DERESP, MD_NOVA + 'DERESP\n'),
                        (NOME_RESP, '# REsp não admitido\n'), (NOME_COPIA, MD_SENTENCA + ' '), (NOME_RE, '# RE não admitido\n'),
                        ('perdido.md', '# sem linha no índice\n')]:
        (dec / extraido(nome, 'cp866' if nome == NOME_SENTENCA else None)).write_text(texto, encoding='utf-8')
    for nome, texto in [(NOME_IMPUG, MD_IMPUG), (NOME_APELACAO, MD_APELACAO)]:
        (pet / extraido(nome, 'cp437' if nome == NOME_APELACAO else None)).write_text(texto, encoding='utf-8')

    cab = ('Arquivo .md\tData\tTipo\tTipo (como no nome do arquivo)\tEmbargos de declaração\tParte (abreviada)'
           '\tProcesso\tPáginas\tPáginas com OCR\tPalavras conferidas %\tNúmeros conferidos\tPDF de origem')
    linhas = [
        # casa pelo nome do PDF da planilha
        f'{NOME_SENTENCA}\t20/05/2019\tSENTENÇA\tSENTENÇA\t\tEMBRACON\t5007301-28.2019.4.04.7200\t9\t0\t100.0\t56/56'
        '\t20_05_2019 - SENTENÇA - EMBRACON - 5007301-28.2019.4.04.7200.pdf',
        # PDF de origem com outro nome: casa por processo + instância + data; "07/jul" do Excel
        f'{NOME_EMBARGOS}\t21/08/2019\tSENTENÇA\tSENTENÇAED\tsim\tEMBRACON\t5007301-28.2019.4.04.7200\t2\t0\t100.0'
        '\t07/jul\tnome-diferente.pdf',
        # decisão que já tem PDF: não troca
        f'{NOME_ACORDAO}\t26/06/2026\tACÓRDÃO\tACÓRDÃO\t\tSANTOS BRASIL\t5001181-56.2023.4.03.6100\t30\t30\t97.5'
        '\t10/12\t26_06_2026 - ACÓRDÃO - SANTOS BRASIL.pdf',
        # não existe na base: fila da IA
        f'{NOME_NOVA}\t10/01/2020\tSENTENÇA\tSENTENÇA\t\tNOVA\t5000001-11.2020.4.04.7000\t1\t0\t100.0\t1/1\tnova.pdf',
        # Tipo vazio no índice (DERESP): casa por processo + data
        f'{NOME_DERESP}\t15/02/2026\t\t\t\tDERESP\t5006656-95.2022.4.04.7200\t6\t0\t100.0\t85/85'
        '\t15_02_2026 - DERESP - KHRONOS - 5006656-95.2022.4.04.7200.pdf',
        # Segunda cópia do PDF da mesma sentença, com outro nome: mesma chave da base
        f'{NOME_COPIA}\t20/05/2019\tSENTENÇA\tSENTENÇA\t\tEMBRACON\t5007301-28.2019.4.04.7200\t9\t0\t100.0\t56/56'
        '\tSentença - EMBRACON.pdf',
        # Mesmo processo e dia, duas decisões (REsp e RE); a do RE casa pelo nome
        # e vem DEPOIS no índice — a do REsp não pode tomar o lugar dela.
        f'{NOME_RESP}\t16/02/2026\t\t\t\tLOJAS\t5000003-11.2021.4.04.7000\t6\t0\t100.0\t1/1\tDERESP - LOJAS.pdf',
        f'{NOME_RE}\t16/02/2026\t\t\t\tLOJAS\t5000003-11.2021.4.04.7000\t4\t0\t100.0\t1/1\tDERE - LOJAS.pdf',
        # .md que não está na pasta
        'sumido.md\t01/01/2020\tSENTENÇA\tSENTENÇA\t\tX\t5000002-11.2020.4.04.7000\t1\t0\t100.0\t1/1\tsumido.pdf',
    ]
    # Excel brasileiro salva em cp1252.
    (dec / '_INDICE_decisoes.csv').write_bytes(('\r\n'.join([cab] + linhas) + '\r\n').encode('cp1252'))

    cab = ('Nº\tAutora\tTribunal\tÓrgão julgador\tPeça\tProtocolo\tTeses\tArquivo .md\tSituação\tPáginas'
           '\tPáginas com OCR\tPalavras conferidas %\tNúmeros conferidos\tPDF de origem\tLink')
    teses = 'DA PRESCRIÇÃO. OBS.: SÚMULA 625/STJ INAPLICÁVEL; TRAJETO (B91 E B94). OBS.: RESOLUÇÃO CNPS 1.329/2017'
    linhas = [
        f'487\tCNH INDUSTRIAL BRASIL LTDA. (2016-2024)\tTRF-6\t19ª Vara Federal Cível de Belo Horizonte/MG'
        f'\tIMPUGNAÇÃO À CONTESTAÇÃO\t09/10/2026\t{teses}\t{NOME_IMPUG}\tconvertido\t33\t17\t100.0\t226/226'
        '\tG:\\Drives compartilhados\\CNH\\Impugnação.pdf\thttps://drive.google.com/file/d/1NxLdsJ597El3ZqAdGjyh-djXWYA-GZVx/view?usp=sharing',
        f'486\tCOAMO AGROINDUSTRIAL COOPERATIVA (2023)\tTRF-4\t1ª Vara Federal de Campo Mourão/PR\tAPELAÇÃO'
        f'\t09/10/2026\tSÍNTESE RECURSAL\t{NOME_APELACAO}\tconvertido\t18\t2\t100.0\t115/115\tG:\\x.pdf'
        '\thttps://drive.google.com/file/d/1kICuNt_aqQrJQpj4d7SvfhWYlEUBLNG0/view?usp=sharing',
        '485\tBUGIO\tTRF-4\tVara\tCONTRARRAZÕES À APELAÇÃO\t09/10/2026\tX\tbugio.md\tfalhou\t7\t2\t\t\t\t',
    ]
    (pet / '_INDICE_peticoes.csv').write_text('\n'.join([cab] + linhas) + '\n', encoding='utf-8-sig')


def assinaturas():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in PASTA.rglob('*') if p.is_file()}


def setup():
    db.drop_all()
    db.create_all()
    db.session.add(LawFirm(id=1, name='Escritório', cnpj='00000000000191'))
    db.session.add(User(id=1, law_firm_id=1, name='Admin', email='a@b.c', password_hash='x', role='admin'))
    db.session.add(JurisprudenceDecision(
        id=10, law_firm_id=1, processo='5007301-28.2019.4.04.7200', processo_digits='50073012820194047200',
        tipo_documento='sentenca', data_julgamento=date(2019, 5, 20),
        original_filename='20_05_2019 - SENTENÇA - EMBRACON - 5007301-28.2019.4.04.7200.pdf'))
    db.session.add(JurisprudenceDecision(
        id=11, law_firm_id=1, processo='5007301-28.2019.4.04.7200', processo_digits='50073012820194047200',
        tipo_documento='embargos', data_julgamento=date(2019, 8, 21), original_filename='outro nome.pdf'))
    db.session.add(JurisprudenceDecision(
        id=12, law_firm_id=1, processo='5001181-56.2023.4.03.6100', processo_digits='50011815620234036100',
        tipo_documento='acordao', data_julgamento=date(2026, 6, 26), pdf_path='/algum/lugar.pdf',
        original_filename='26_06_2026 - ACÓRDÃO - SANTOS BRASIL.pdf'))
    db.session.add(JurisprudenceDecision(
        id=13, law_firm_id=1, processo='5006656-95.2022.4.04.7200', processo_digits='50066569520224047200',
        tipo_documento='acordao', data_julgamento=date(2026, 2, 15),
        original_filename='15_02_2026 - DERE - KHRONOS - 5006656-95.2022.4.04.7200.pdf'))
    db.session.add(JurisprudenceDecision(
        id=14, law_firm_id=1, processo='5000003-11.2021.4.04.7000', processo_digits='50000031120214047000',
        tipo_documento='acordao', data_julgamento=date(2026, 2, 16), original_filename='DERE - LOJAS.pdf'))
    # Decisão de outro escritório com o mesmo nome de PDF: nunca pode casar.
    db.session.add(LawFirm(id=2, name='Outro', cnpj='00000000000272'))
    db.session.add(JurisprudenceDecision(
        id=20, law_firm_id=2, processo='5000001-11.2020.4.04.7000', processo_digits='50000011120204047000',
        tipo_documento='sentenca', data_julgamento=date(2020, 1, 10), original_filename='nova.pdf'))
    db.session.commit()


def por_arquivo(itens, nome, acao=None):
    return [i for i in itens if i.arquivo == nome and (acao is None or i.acao == acao)]


def test_plano():
    print('\nConferência (nada gravado)')
    itens = lote.planejar(str(PASTA), 1)
    acoes = {(i.arquivo, i.acao) for i in itens}

    check('sentença casa pelo nome do PDF da planilha', (NOME_SENTENCA, lote.ANEXAR) in acoes)
    sentenca = por_arquivo(itens, NOME_SENTENCA)[0]
    check('… com a decisão certa', sentenca.dados.get('decisoes') == [10], sentenca.dados)
    embargos = por_arquivo(itens, NOME_EMBARGOS)[0]
    check('embargos casam por processo + instância + data ("sim" na coluna ED)',
          embargos.acao == lote.ANEXAR and embargos.dados.get('decisoes') == [11], (embargos.acao, embargos.dados))
    deresp = por_arquivo(itens, NOME_DERESP)[0]
    check('índice sem instância casa por processo + data (nome cortado na planilha)',
          deresp.acao == lote.ANEXAR and deresp.dados.get('decisoes') == [13], (deresp.acao, deresp.dados))
    re_, resp = por_arquivo(itens, NOME_RE)[0], por_arquivo(itens, NOME_RESP)[0]
    check('o RE fica com a decisão que casa pelo nome, mesmo vindo depois no índice',
          re_.acao == lote.ANEXAR and re_.dados.get('decisoes') == [14], (re_.acao, re_.dados))
    check('… e o REsp do mesmo dia vai para a IA, não é pulado', resp.acao == lote.LER_IA, (resp.acao, resp.motivo))
    copia = por_arquivo(itens, NOME_COPIA)[0]
    check('segunda cópia da mesma decisão é pulada sem IA (processo + instância + data)',
          copia.acao == lote.PULAR and copia.motivo.startswith('mesma decisão de outra linha'), (copia.acao, copia.motivo))
    acordao = por_arquivo(itens, NOME_ACORDAO)[0]
    check('decisão que já tem PDF não é trocada', acordao.acao == lote.PULAR and 'já tem arquivo' in acordao.motivo,
          acordao.motivo)
    nova = por_arquivo(itens, NOME_NOVA)[0]
    check('decisão fora da base vai para a IA (a do outro escritório não conta)', nova.acao == lote.LER_IA, nova.acao)
    check('linha cujo .md não está na pasta é relatada',
          any(i.arquivo == 'sumido.md' and 'não encontrado' in i.motivo for i in itens))
    check('arquivo sem linha no índice é relatado',
          any(i.arquivo == 'perdido.md' and i.motivo == 'arquivo fora do índice CSV' for i in itens))

    check('impugnação vai para a Base de Conhecimento', (NOME_IMPUG, lote.BASE_CONHECIMENTO) in acoes)
    check('… e também para as Peças-modelo', (NOME_IMPUG, lote.PECA_MODELO) in acoes)
    check('apelação vai só para a Base de Conhecimento',
          {i.acao for i in por_arquivo(itens, NOME_APELACAO)} == {lote.BASE_CONHECIMENTO})
    check('linha não convertida é pulada com o motivo',
          any(i.arquivo == 'bugio.md' and 'falhou' in i.motivo for i in itens))
    peca = por_arquivo(itens, NOME_IMPUG, lote.PECA_MODELO)[0]
    check('id do Drive sai do Link', peca.dados['drive_id'] == '1NxLdsJ597El3ZqAdGjyh-djXWYA-GZVx',
          peca.dados['drive_id'])
    check('teses inteiras, com os ";" de dentro', peca.dados['teses'].endswith('1.329/2017'))
    sem = lote.filtrar(itens, sem_pecas=True)
    so = lote.filtrar(itens, so_pecas=True)
    check('--sem-pecas tira só as peças-modelo; a impugnação continua indo para a Base',
          not any(i.acao == lote.PECA_MODELO for i in sem) and (NOME_IMPUG, lote.BASE_CONHECIMENTO) in
          {(i.arquivo, i.acao) for i in sem} and any(i.origem == 'decisao' for i in sem))
    check('--so-pecas deixa só as peças-modelo', so and all(i.destino == lote.DESTINO_PECAS for i in so)
          and (NOME_IMPUG, lote.PECA_MODELO) in {(i.arquivo, i.acao) for i in so})
    check('as duas rodadas juntas cobrem o plano inteiro de petições sem repetir',
          len(lote.filtrar(itens, so='peticoes', sem_pecas=True)) + len(so) == len(lote.filtrar(itens, so='peticoes')))
    try:
        lote.filtrar(itens, sem_pecas=True, so_pecas=True)
        check('--sem-pecas com --so-pecas é recusado', False)
    except ValueError:
        check('--sem-pecas com --so-pecas é recusado', True)
    check('planejar não grava nada',
          (KnowledgeBase.query.count(), ImpugnacaoReferenceModel.query.count(), JurisprudenceUpload.query.count())
          == (0, 0, 0))
    return itens


def test_execucao(itens):
    print('\nGravação')
    antes = assinaturas()
    indexadas = []

    def indexar_falso(decisao):
        indice.guardar_texto(decisao, indice.extrair_paginas(decisao.pdf_path))
        indexadas.append(decisao.id)

    original, indice.preparar_e_indexar = indice.preparar_e_indexar, indexar_falso
    na_base = []

    def ingerir_falso(arquivo, dados):
        na_base.append((arquivo.id, arquivo.processing_status))
        if 'APELAÇÃO' in (dados.get('peca') or '') and not na_base_falhou:
            na_base_falhou.append(arquivo.id)
            raise RuntimeError('Qdrant fora do ar')
        return 3

    na_base_falhou = []
    ingerir_original, lote._ingerir_na_base = lote._ingerir_na_base, ingerir_falso
    disparos = []
    disparar_original, envios.disparar = envios.disparar, lambda *a, **k: disparos.append(a)
    cwd = os.getcwd()
    os.chdir(TMP)  # peças e base gravam em uploads/ relativo
    try:
        lote.executar(itens, 1, 1, processar_pecas=False, paralelo=3)
    finally:
        os.chdir(cwd)
        indice.preparar_e_indexar = original
        lote._ingerir_na_base = ingerir_original
        envios.disparar = disparar_original

    erros = [i.arquivo for i in itens if i.resultado.startswith('ERRO')]
    check('só a falha simulada de indexação', erros == [NOME_APELACAO], erros)
    check('pasta de origem intacta, byte a byte', assinaturas() == antes)

    d10 = db.session.get(JurisprudenceDecision, 10)
    check('nome estragado pelo unzip no disco', any('├' in p.name for p in PASTA.rglob('*.md')))
    check('decisão 10 recebeu o .md', bool(d10.pdf_path) and d10.pdf_path.endswith('.md'), d10.pdf_path)
    check('… cópia idêntica ao original', Path(d10.pdf_path).read_text(encoding='utf-8') == MD_SENTENCA)
    check('… mantém o nome do PDF da planilha', d10.original_filename.endswith('.pdf'), d10.original_filename)
    check('… inteiro teor lido do .md e indexado', 10 in indexadas and 'procedente' in (d10.texto_integral or ''))
    check('decisão 12 (já tinha PDF) ficou como estava',
          db.session.get(JurisprudenceDecision, 12).pdf_path == '/algum/lugar.pdf')

    upload = JurisprudenceUpload.query.filter_by(original_filename=NOME_NOVA).one()
    check('decisão nova na fila, sem disparar thread (script mataria no meio)',
          upload.status == JurisprudenceUpload.STATUS_QUEUED and not disparos, (upload.status, disparos))
    check('… com o nome do .md como veio', upload.original_filename == NOME_NOVA, upload.original_filename)

    kb = {k.original_filename: k for k in KnowledgeBase.query.all()}
    check('… e o arquivo copiado leva o nome do índice, não o estragado', '├' not in d10.pdf_path, d10.pdf_path)
    check('duas petições na Base de Conhecimento, com o nome do índice (acentos)',
          set(kb) == {NOME_IMPUG, NOME_APELACAO}, list(kb))
    k = kb[NOME_IMPUG]
    check('… já entra concluída, sem passar pelo process_knowledge_base',
          (k.processing_status, k.file_type, k.processed_at is not None) == ('completed', 'MD', True),
          (k.processing_status, k.file_type))
    check('… indexada como "processing" (o cron só pega "pending")', (k.id, 'processing') in na_base, na_base)
    check('… com o link do Drive do índice (o PDF protocolado)',
          k.source_url == 'https://drive.google.com/file/d/1NxLdsJ597El3ZqAdGjyh-djXWYA-GZVx/view?usp=sharing',
          k.source_url)
    check('… com o número do processo lido do texto (o CSV não traz)',
          k.lawsuit_number == '6074477-21.2026.4.06.3800', k.lawsuit_number)
    check('… categoria e tags do índice', (k.category, k.tags) == ('Petições protocoladas', 'IMPUGNAÇÃO À CONTESTAÇÃO'),
          (k.category, k.tags))
    falhou = kb[NOME_APELACAO]
    check('falha na indexação vira "error" com o motivo',
          falhou.processing_status == 'error' and 'Qdrant fora do ar' in (falhou.processing_error_message or ''),
          (falhou.processing_status, falhou.processing_error_message))
    check('… descrição com autora, peça, OCR e teses',
          all(t in k.description for t in ('CNH INDUSTRIAL', 'IMPUGNAÇÃO', 'OCR em 17 de 33', 'SÚMULA 625')),
          k.description)
    check('… cópia idêntica', Path(TMP / k.file_path).read_text(encoding='utf-8') == MD_IMPUG)

    peca = ImpugnacaoReferenceModel.query.one()
    check('impugnação virou peça-modelo ligada ao Drive',
          peca.source_drive_file_id == '1NxLdsJ597El3ZqAdGjyh-djXWYA-GZVx', peca.source_drive_file_id)
    check('… com tribunal, órgão, autora e teses da planilha',
          (peca.trf_region, peca.case_name, peca.file_type) == ('TRF6', 'CNH INDUSTRIAL BRASIL LTDA. (2016-2024)', 'md')
          and peca.orgao_julgador.startswith('19ª Vara') and peca.source_theses_json[0].startswith('DA PRESCRIÇÃO'),
          (peca.trf_region, peca.case_name, peca.orgao_julgador))


def test_segunda_rodada():
    print('\nRodar de novo')
    peca = ImpugnacaoReferenceModel.query.one()
    peca.ingestion_status = 'completed'   # a gravação do teste não processou a peça (sem IA)
    db.session.commit()
    itens = lote.planejar(str(PASTA), 1)
    acionaveis = [(i.arquivo, i.acao) for i in itens if i.acao != lote.PULAR]
    check('só volta o que falhou na Base', acionaveis == [(NOME_APELACAO, lote.BASE_CONHECIMENTO)], acionaveis)
    falhou = KnowledgeBase.query.filter_by(original_filename=NOME_APELACAO).one()
    lote._ingerir_na_base, original = (lambda arquivo, dados: 2), lote._ingerir_na_base
    try:
        lote.executar(itens, 1, 1)
    finally:
        lote._ingerir_na_base = original
    check('… e reaproveita a mesma linha, sem duplicar',
          KnowledgeBase.query.filter_by(original_filename=NOME_APELACAO).count() == 1
          and db.session.get(KnowledgeBase, falhou.id).processing_status == 'completed')
    itens = lote.planejar(str(PASTA), 1)
    acionaveis = [(i.arquivo, i.acao) for i in itens if i.acao != lote.PULAR]
    check('nada é importado duas vezes', not acionaveis, acionaveis)
    nova = por_arquivo(itens, NOME_NOVA)[0]
    check('decisão nova reconhecida pela fila', 'já enviado à fila' in nova.motivo, nova.motivo)


def test_link_e_retomada():
    print('\nLink do Drive e peça interrompida')
    k = KnowledgeBase.query.filter_by(original_filename=NOME_IMPUG).one()
    k.source_url = None                     # entrou antes de a coluna existir
    peca = ImpugnacaoReferenceModel.query.one()
    peca.ingestion_status = 'processing'    # script morto no meio da indexação
    db.session.commit()
    itens = lote.planejar(str(PASTA), 1)
    acoes = [(i.arquivo, i.acao, i.alvo_id) for i in itens if i.acao != lote.PULAR]
    check('peça interrompida volta para a mesma linha', acoes == [(NOME_IMPUG, lote.PECA_MODELO, peca.id)], acoes)
    check('arquivo sem link é marcado para completar',
          any(i.dados.get('completar_link') and i.alvo_id == k.id for i in itens))
    marcados = [(i.acao, i.alvo_id) for i in itens if i.dados.get('completar_link')]
    check('… só a linha da Base, nunca a da peça-modelo (ids de tabelas diferentes)',
          marcados == [(lote.PULAR, k.id)], marcados)
    ingeridas = []
    import app.services.impugnacao_reference_ingestion as ingestao
    original = ingestao.ingest_reference

    def ingest_falso(law_firm_id, ref_id, **_):
        ingeridas.append(ref_id)
        ref = db.session.get(ImpugnacaoReferenceModel, ref_id)
        ref.ingestion_status = 'completed'
        db.session.commit()

    ingestao.ingest_reference = ingest_falso
    try:
        lote.executar(itens, 1, 1)
    finally:
        ingestao.ingest_reference = original
    check('… retomada sem criar outra peça',
          ingeridas == [peca.id] and ImpugnacaoReferenceModel.query.count() == 1, ingeridas)
    check('link preenchido sem reindexar', db.session.get(KnowledgeBase, k.id).source_url.startswith('https://drive'))


def test_processo_do_texto():
    print('\nNúmero do processo no texto')
    casos = [
        ('cab\n\n---\n\nEXCELENTÍSSIMO\n\nProcesso nº 5052299-94.2022.4.04.7000\n\nTRF4 AC 5003321-10.2023.4.04.7000',
         '5052299-94.2022.4.04.7000', 'rotulado vence o precedente'),
        ('cab\n\n---\n\nVide 5003321-10.2023.4.04.7000 (precedente).\n\nAutos n.º 50109013720224047108',
         '5010901-37.2022.4.04.7108', 'rótulo "Autos", número sem pontuação, mesmo depois de outro número'),
        ('cab\n\n---\n\nEXCELENTÍSSIMO\n\n5015482-56.2021.4.04.7100\n\nSTEMAC', '5015482-56.2021.4.04.7100',
         'sem rótulo, logo no início'),
        ('cab\n\n---\n\n' + 'texto ' * 200 + 'cita 5015482-56.2021.4.04.7100', None, 'número solto lá no meio não conta'),
        ('**PDF no Drive:** 1234567-89.2020.4.04.7000\n\n---\n\nsem número', None, 'cabeçalho do .md é pulado'),
        ('cab\n\n---\n\n' + 'Tabela de benefícios… ' * 250 + '\n\nEXCELENTÍSSIMO(A) JUIZ(A)\n\nProcesso nº 6074477-21.2026.4.06.3800',
         '6074477-21.2026.4.06.3800', 'endereçamento lá adiante no texto (25 do lote)'),
        ('cab\n\n---\n\n**ORIGEM**: TRF4 **PROCESSO DE ORIGEM**: 5006656-95.2022.4.04.7200', '5006656-95.2022.4.04.7200',
         'rótulo "processo de origem" em negrito'),
        ('cab\n\n---\n\nEXCELENTÍSSIMO JUIZ\n\nProcesso nº \n\nIMPUGNAÇÃO', None, '"Processo nº" sem número fica sem número'),
    ]
    for texto, esperado, rotulo in casos:
        obtido = lote.processo_do_texto(texto)
        check(rotulo, obtido == esperado, obtido)


def test_embeddings_em_lote():
    print('\nEmbeddings em lote')
    from types import SimpleNamespace
    from app.agents.knowledge_base.knowledge_ingestion_agent import embed_many
    chamadas = []

    class ClienteFalso:
        class embeddings:
            @staticmethod
            def create(input, model):
                chamadas.append(len(input))
                # a API não promete a ordem da lista: o índice é que manda
                dados = [SimpleNamespace(index=i, embedding=[float(len(t))]) for i, t in enumerate(input)]
                return SimpleNamespace(data=list(reversed(dados)))

    textos = ['a' * n for n in range(1, 151)]
    vetores = embed_many(ClienteFalso, textos, 'modelo', batch_size=64)
    check('uma chamada por lote de 64', chamadas == [64, 64, 22], chamadas)
    check('vetores na ordem dos textos', [v[0] for v in vetores] == [float(n) for n in range(1, 151)])
    check('lista vazia não chama a API', embed_many(ClienteFalso, [], 'modelo') == [] and len(chamadas) == 3)


def test_relatorio(itens):
    print('\nRelatório')
    caminho = TMP / 'relatorio.csv'
    lote.gravar_relatorio(itens, str(caminho))
    linhas = caminho.read_text(encoding='utf-8-sig').splitlines()
    check('uma linha por item + cabeçalho', len(linhas) == len(itens) + 1, len(linhas))
    check('abre no Excel (separador ;)', linhas[0].startswith('Origem;Linha do índice;'))


def test_pasta_errada():
    print('\nPasta errada')
    vazia = TMP / 'vazia'
    vazia.mkdir()
    for pasta in (vazia, TMP / 'nao-existe'):
        try:
            lote.planejar(str(pasta), 1)
            check(f'recusa {pasta.name}', False)
        except lote.LoteInvalido as erro:
            check(f'recusa {pasta.name} com mensagem', bool(str(erro)), erro)


def main():
    montar_lote()
    with app.app_context():
        setup()
        itens = test_plano()
        test_execucao(itens)
        test_segunda_rodada()
        test_link_e_retomada()
        test_relatorio(itens)
        test_embeddings_em_lote()
        test_processo_do_texto()
        test_pasta_errada()
    if FALHAS:
        print(f'\n❌ {len(FALHAS)} falha(s): {FALHAS}')
        return 1
    print('\n✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    finally:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
        shutil.rmtree(TMP, ignore_errors=True)
