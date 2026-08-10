#!/usr/bin/env python3
"""
Testes da ingestão do DOU (app/services/dou_ingestion_service.py).

Não toca a rede: um client falso devolve ZIPs montados em memória. Cobre o
que mais importa no módulo — idempotência e republicação.

    uv run python tests/test_dou_ingestion.py
"""

import io
import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, DouEdition, DouArticle
from app.services import dou_ingestion_service as ingestion
from app.services import dou_search_service as busca

FIXTURES = Path(__file__).resolve().parent / 'fixtures'

# Data-sentinela, deliberadamente impossível: o DOU eletrônico não existe em
# 1970 e o INLABS nunca terá essa edição. A primeira versão deste teste usava a
# data corrente e, na limpeza, apagou do banco uma captura real — além de
# sobrescrever os ZIPs verdadeiros em uploads/dou/ com as fixtures. Teste que
# grava em caminho de produção precisa de uma chave que jamais colida com dado
# de verdade.
DATA_TESTE = date(1970, 1, 1)

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def montar_zip(*xmls: bytes) -> bytes:
    """Monta um ZIP em memória com um arquivo .xml por matéria, como o INLABS."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for i, conteudo in enumerate(xmls):
            z.writestr(f'materia_{i}.xml', conteudo)
    return buffer.getvalue()


class FakeClient:
    """Duplo do InlabsClient: devolve ZIPs fixos, sem rede."""

    def __init__(self, zips: dict, pdfs: dict | None = None):
        self.zips = zips        # {(data, secao): bytes | None}
        self.pdfs = pdfs or {}

    def login(self):
        pass

    def download_xml_zip(self, data, secao):
        return self.zips.get((data, secao))

    def download_pdf(self, data, secao):
        return self.pdfs.get((data, secao.lower()))


def limpar_dados_de_teste():
    """Remove o resíduo da data-sentinela — banco, índice e arquivos.

    Só toca DATA_TESTE (1970-01-01). Nunca apagar por outro critério: a versão
    anterior removia execuções por ``modo``, o que alcançava execuções reais.

    O índice também precisa ser limpo: ``ingest_date`` indexa no índice de
    produção, e apagar só do MySQL deixava documentos órfãos aparecendo na
    busca — inclusive em primeiro lugar, porque a fixture fala de "Fator
    Acidentário de Prevenção".
    """
    ids = [a.id for a in DouArticle.query.join(DouEdition)
           .filter(DouEdition.data_publicacao == DATA_TESTE).all()]

    for edicao in DouEdition.query.filter_by(data_publicacao=DATA_TESTE).all():
        db.session.delete(edicao)
    db.session.commit()

    if ids:
        busca.remove_articles(ids)

    diretorio = ingestion.storage_dir(DATA_TESTE)
    if diretorio.exists():
        shutil.rmtree(diretorio.parent.parent, ignore_errors=True)  # uploads/dou/1970


def test_ingestao_basica():
    print('\n1. Ingestão de um ZIP com duas matérias')
    limpar_dados_de_teste()

    xml_a = (FIXTURES / 'dou_sample_article.xml').read_bytes()
    xml_b = (FIXTURES / 'dou_sample_minimo.xml').read_bytes()
    zip_bytes = montar_zip(xml_a, xml_b)

    client = FakeClient({(DATA_TESTE, 'DO1'): zip_bytes})
    resultado = ingestion.ingest_date(DATA_TESTE, secoes=['DO1'], with_pdf=False, client=client)

    check('relata 2 matérias inseridas',
          resultado['materias_inseridas'] == 2, str(resultado))
    check('relata 0 atualizadas', resultado['materias_atualizadas'] == 0, str(resultado))

    edicao = DouEdition.query.filter_by(data_publicacao=DATA_TESTE, secao='DO1').first()
    check('criou a edição', edicao is not None)
    check('status ficou parsed', edicao.status == DouEdition.STATUS_PARSED, edicao.status)
    check('qtd_materias = 2', edicao.qtd_materias == 2, str(edicao.qtd_materias))
    check('gravou content_signature', bool(edicao.content_signature))
    check('zip_path é relativo',
          edicao.zip_path.startswith('uploads/dou/'), repr(edicao.zip_path))
    check('arquivo existe em disco', Path(edicao.zip_path).exists(), edicao.zip_path)

    artigos = DouArticle.query.filter_by(edition_id=edicao.id).all()
    check('2 matérias no banco', len(artigos) == 2, str(len(artigos)))
    check('desnormalizou pub_date', all(a.pub_date is not None or a.pub_name == 'DO3' for a in artigos))


def test_idempotencia():
    print('\n2. Idempotência: reingerir o mesmo ZIP não duplica')
    xml_a = (FIXTURES / 'dou_sample_article.xml').read_bytes()
    zip_bytes = montar_zip(xml_a)

    client = FakeClient({(DATA_TESTE, 'DO2'): zip_bytes})
    ingestion.ingest_date(DATA_TESTE, secoes=['DO2'], with_pdf=False, client=client)
    antes = DouArticle.query.join(DouEdition).filter(
        DouEdition.data_publicacao == DATA_TESTE, DouEdition.secao == 'DO2'
    ).count()

    segundo = ingestion.ingest_date(DATA_TESTE, secoes=['DO2'], with_pdf=False, client=client)
    depois = DouArticle.query.join(DouEdition).filter(
        DouEdition.data_publicacao == DATA_TESTE, DouEdition.secao == 'DO2'
    ).count()

    check('mesma contagem de matérias', antes == depois, f'{antes} → {depois}')
    check('nada foi inserido na segunda vez',
          segundo['materias_inseridas'] == 0, str(segundo))
    check('assinatura igual pula o reprocesso',
          segundo.get('inalterado') is True, str(segundo))


def test_republicacao():
    print('\n3. Republicação: conteúdo diferente atualiza, não duplica')
    xml_a = (FIXTURES / 'dou_sample_article.xml').read_bytes()
    xml_alterado = xml_a.replace(b'Fica aprovado', b'Fica revogado')

    client1 = FakeClient({(DATA_TESTE, 'DO3'): montar_zip(xml_a)})
    ingestion.ingest_date(DATA_TESTE, secoes=['DO3'], with_pdf=False, client=client1)

    client2 = FakeClient({(DATA_TESTE, 'DO3'): montar_zip(xml_alterado)})
    resultado = ingestion.ingest_date(DATA_TESTE, secoes=['DO3'], with_pdf=False, client=client2)

    edicao = DouEdition.query.filter_by(data_publicacao=DATA_TESTE, secao='DO3').first()
    artigos = DouArticle.query.filter_by(edition_id=edicao.id).all()

    check('continua com 1 matéria (UPDATE, não INSERT)', len(artigos) == 1, str(len(artigos)))
    check('relata 1 atualizada', resultado['materias_atualizadas'] == 1, str(resultado))
    check('texto novo foi gravado', 'revogado' in artigos[0].texto, artigos[0].texto[:80])
    check('hash mudou junto', artigos[0].hash is not None)


def test_nao_publicado():
    print('\n4. Seção não publicada (404) não é erro')
    client = FakeClient({})  # tudo devolve None
    resultado = ingestion.ingest_date(DATA_TESTE, secoes=['DO1E'], with_pdf=False, client=client)

    check('contabiliza como não publicado',
          resultado['nao_publicados'] == 1, str(resultado))
    check('não conta como erro', resultado['erros'] == 0, str(resultado))

    edicao = DouEdition.query.filter_by(data_publicacao=DATA_TESTE, secao='DO1E').first()
    check('registra a edição como not_published',
          edicao is not None and edicao.status == DouEdition.STATUS_NOT_PUBLISHED,
          edicao.status if edicao else 'sem edição')


def test_dry_run():
    print('\n5. dry-run não grava nada')
    limpar_dados_de_teste()
    xml_a = (FIXTURES / 'dou_sample_article.xml').read_bytes()
    client = FakeClient({(DATA_TESTE, 'DO1'): montar_zip(xml_a)})

    ingestion.ingest_date(DATA_TESTE, secoes=['DO1'], with_pdf=False,
                          dry_run=True, client=client)

    check('nenhuma edição criada',
          DouEdition.query.filter_by(data_publicacao=DATA_TESTE).count() == 0)


def test_conteudo_nao_e_zip():
    """Bytes que não são ZIP não podem virar arquivo em disco nem traceback.

    A gravação acontecia antes do parse e o rollback do banco não desfaz
    escrita em disco: quando o INLABS devolveu a página HTML do portal para
    datas de fim de semana, ficaram 12 arquivos .zip que eram HTML de 37 KB.
    """
    print('\n7. Resposta que não é ZIP não deixa lixo em disco')
    limpar_dados_de_teste()

    lixo = b'<!DOCTYPE html>\r\n<html><head><title>Imprensa Nacional</title></head></html>'
    client = FakeClient({(DATA_TESTE, 'DO1'): lixo})

    resultado = ingestion.ingest_date(DATA_TESTE, secoes=['DO1'],
                                      with_pdf=False, client=client)

    check('contabiliza como erro, sem estourar', resultado['erros'] == 1, str(resultado))
    check('nenhuma matéria inserida', resultado['materias_inseridas'] == 0, str(resultado))

    caminho = ingestion.storage_dir(DATA_TESTE) / '1970-01-01-DO1.zip'
    check('nada foi gravado em disco', not caminho.exists(), str(caminho))

    edicao = DouEdition.query.filter_by(data_publicacao=DATA_TESTE, secao='DO1').first()
    check('edição fica marcada como erro',
          edicao is not None and edicao.status == DouEdition.STATUS_ERROR,
          edicao.status if edicao else 'sem edição')
    check('a mensagem explica o que veio',
          edicao is not None and 'não é um ZIP' in (edicao.error_message or ''),
          edicao.error_message if edicao else '')

    limpar_dados_de_teste()


def test_limpeza_nao_deixa_fantasma_no_indice():
    """Matéria apagada do banco tem de sair do índice também.

    ``ingest_date`` indexa no índice de produção. Quando a limpeza só apagava
    do MySQL, ficavam documentos órfãos que apareciam na busca e levavam a
    404 — e, como esta fixture fala de "Fator Acidentário de Prevenção", eles
    apareciam em PRIMEIRO lugar na consulta mais importante do domínio.
    """
    print('\n8. Limpeza remove do índice, não só do banco')
    if not busca.is_available():
        print('  ⏭️  Meilisearch não responde — pulando')
        return

    # Esperar a fila antes de medir: a exclusão do Meilisearch é assíncrona, e
    # ler o tamanho logo após a limpeza pegava documentos ainda em remoção.
    limpar_dados_de_teste()
    busca.aguardar_indexacao()
    antes = busca.get_index().get_stats().number_of_documents

    xml_a = (FIXTURES / 'dou_sample_article.xml').read_bytes()
    client = FakeClient({(DATA_TESTE, 'DO1'): montar_zip(xml_a)})
    ingestion.ingest_date(DATA_TESTE, secoes=['DO1'], with_pdf=False, client=client)
    busca.aguardar_indexacao()

    durante = busca.get_index().get_stats().number_of_documents
    check('a ingestão indexou a matéria de teste', durante > antes,
          f'{antes} -> {durante}')

    limpar_dados_de_teste()
    busca.aguardar_indexacao()
    depois = busca.get_index().get_stats().number_of_documents

    check('a limpeza devolveu o índice ao tamanho original', depois == antes,
          f'{antes} -> {durante} -> {depois}')

    with app.app_context():
        no_banco = DouArticle.query.count()
    check('índice e banco batem', depois == no_banco, f'índice {depois} x banco {no_banco}')


def test_storage_dir():
    print('\n6. Caminho de armazenamento')
    caminho = ingestion.storage_dir(date(2026, 8, 10))
    check('caminho relativo por ano/mês/dia',
          str(caminho) == 'uploads/dou/2026/08/10', str(caminho))
    check('não é absoluto', not caminho.is_absolute(), str(caminho))


def main():
    print('=' * 60)
    print('TESTES DA INGESTÃO DO DOU')
    print('=' * 60)

    with app.app_context():
        test_ingestao_basica()
        test_idempotencia()
        test_republicacao()
        test_nao_publicado()
        test_dry_run()
        test_conteudo_nao_e_zip()
        test_limpeza_nao_deixa_fantasma_no_indice()
        test_storage_dir()
        limpar_dados_de_teste()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
