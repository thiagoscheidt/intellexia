#!/usr/bin/env python3
"""
Importação automática das petições protocoladas compartilhadas pelo Google Drive.

Sem rede e sem IA: o Drive é um dublê que lista e "baixa" PDFs gerados aqui,
o agente devolve fichas prontas e a indexação (Qdrant/Meilisearch e peça-modelo)
é trocada por um contador. Escritório descartável, removido no fim.

    uv run python tests/test_drive_peticoes.py
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz

from main import app
from app.agents.drive import peticao_protocolada_agent as agente_mod
from app.models import (
    db, DriveIngestion, ImpugnacaoReferenceModel, KnowledgeBase, LawFirm, User, UserPageVisit,
)
from app.services import drive_peticao_service as svc
from app.services import lote_md_import_service as lote

CNPJ = '00000000001199'
_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _pdf(caminho: str, texto: str) -> None:
    doc = fitz.open()
    pagina = doc.new_page()
    pagina.insert_textbox(fitz.Rect(40, 40, 560, 800), texto, fontsize=9)
    doc.save(caminho)


CORPO = ('EXCELENTÍSSIMO SENHOR JUIZ FEDERAL DA 1ª VARA FEDERAL DE CAMPO MOURÃO/PR\n'
         'Processo nº 5004186-40.2026.4.04.7010\nEMPRESA TESTE LTDA., já qualificada... ' + 'texto ' * 120 +
         '\nDA PRESCRIÇÃO\nconforme precedente 0003000-44.2012.4.03.6183...')


class Drive:
    """Dublê: lista metas e "baixa" copiando o PDF gerado para a pasta pedida."""

    def __init__(self, arquivos, pasta_origem):
        self.arquivos, self.pasta = arquivos, pasta_origem
        self.falhar = set()

    def listar(self):
        return [dict(a) for a in self.arquivos]

    def baixar(self, file_id, dest_dir, meta=None):
        from app.services import google_drive_client as gdrive
        if file_id in self.falhar:
            raise gdrive.DriveIndisponivel('O Google Drive está indisponível agora (HTTP 503).')
        os.makedirs(dest_dir, exist_ok=True)
        origem = os.path.join(self.pasta, f'{file_id}.pdf')
        destino = os.path.join(dest_dir, f'{file_id}.pdf')
        shutil.copyfile(origem, destino)
        import hashlib
        return destino, meta['name'], hashlib.sha256(open(destino, 'rb').read()).hexdigest()


class Agente:
    def __init__(self, fichas):
        self.fichas, self.chamadas = fichas, []

    def extrair(self, texto, nome_arquivo, **_):
        self.chamadas.append(nome_arquivo)
        f = self.fichas[nome_arquivo]
        if isinstance(f, Exception):
            raise f
        if len((texto or '').strip()) < 200:
            raise agente_mod.SemTexto('O PDF não tem texto pesquisável (provavelmente escaneado).')
        return f


FICHA = dict(eh_peticao=True, peca='IMPUGNAÇÃO À CONTESTAÇÃO', autora='EMPRESA TESTE LTDA. (2024)',
             tribunal='TRF-4', orgao_julgador='1ª Vara Federal de Campo Mourão/PR', data_protocolo='09/10/2026',
             processo='', teses='DA PRESCRIÇÃO. OBS.: SÚMULA 625/STJ INAPLICÁVEL', observacao='')


def run():
    firm = LawFirm.query.filter_by(cnpj=CNPJ).first()
    if firm:
        _cleanup(firm)
    firm = LawFirm(name='Escritório Teste Drive Petições', cnpj=CNPJ)
    db.session.add(firm)
    db.session.flush()
    admin = User(law_firm_id=firm.id, name='admin', email='admin__test_drive_pet@example.com', role='admin', is_active=True)
    admin.set_password('x')
    db.session.add(admin)
    db.session.flush()
    # Veio pelo lote: Base com o link do Drive no source_url.
    do_lote = KnowledgeBase(user_id=admin.id, law_firm_id=firm.id, original_filename='lote.md', file_path='/x',
                            file_size=1, file_type='MD', category=lote.CATEGORIA_BASE, is_active=True,
                            processing_status='completed',
                            source_url='https://drive.google.com/file/d/IDLOTE000000000000000001/view')
    db.session.add(do_lote)
    db.session.commit()

    pasta = tempfile.mkdtemp()
    arquivos = [
        {'id': 'IDNOVO0000000000000000001', 'name': 'Impugnação à Contestação - Teste _ PROTOCOLO.pdf', 'mimeType': 'application/pdf'},
        {'id': 'IDNOVO0000000000000000002', 'name': 'ED - Teste _ PROTOCOLO.pdf', 'mimeType': 'application/pdf'},
        {'id': 'IDLOTE000000000000000001', 'name': 'Contrarrazões - Lote _ PROTOCOLO.pdf', 'mimeType': 'application/pdf'},
        {'id': 'IDTESTE000000000000000001', 'name': 'TESTE - Documento fictício.pdf', 'mimeType': 'application/pdf'},
        {'id': 'IDSCAN0000000000000000001', 'name': 'Escaneado _ PROTOCOLO.pdf', 'mimeType': 'application/pdf'},
        {'id': 'IDFORA0000000000000000001', 'name': 'Fora do ar _ PROTOCOLO.pdf', 'mimeType': 'application/pdf'},
        {'id': 'IDPASTA000000000000000001', 'name': 'Uma pasta', 'mimeType': 'application/vnd.google-apps.folder'},
    ]
    for a in arquivos[:-1]:
        texto = '' if a['id'].startswith('IDSCAN') else CORPO + a['id']
        _pdf(os.path.join(pasta, f"{a['id']}.pdf"), texto or ' ')
    drive = Drive(arquivos, pasta)
    drive.falhar.add('IDFORA0000000000000000001')
    agente = Agente({
        arquivos[0]['name']: FICHA,
        arquivos[1]['name']: {**FICHA, 'peca': 'EMBARGOS DE DECLARAÇÃO'},
        arquivos[3]['name']: {**FICHA, 'eh_peticao': False, 'observacao': 'documento de teste'},
        arquivos[4]['name']: FICHA,
        arquivos[5]['name']: FICHA,
    })

    indexados, pecas_indexadas = [], []
    orig_ing = lote._ingerir_na_base
    from app.services import impugnacao_reference_ingestion as ref
    orig_ref = ref.ingest_reference
    lote._ingerir_na_base = lambda arquivo, dados: indexados.append(arquivo.id) or 3

    def falso_ref(law_firm_id, ref_id, **kw):
        pecas_indexadas.append(ref_id)
        p = db.session.get(ImpugnacaoReferenceModel, ref_id)
        p.ingestion_status = 'completed'
        db.session.commit()
    ref.ingest_reference = falso_ref
    try:
        print('\n1. Planejar (só lê)')
        planos = svc.planejar(firm.id, drive=drive)
        acoes = {p.meta['id']: p.acao for p in planos}
        check('pasta fica de fora', 'IDPASTA000000000000000001' not in acoes)
        check('o que veio pelo lote: registrar', acoes['IDLOTE000000000000000001'] == svc.REGISTRAR)
        check('novos: importar', acoes['IDNOVO0000000000000000001'] == svc.IMPORTAR)
        check('planejar não chama a IA', agente.chamadas == [])

        print('\n2. Executar')
        svc.executar(firm.id, planos, drive=drive, agente=agente)
        por_id = {p.meta['id']: p for p in planos}

        imp = por_id['IDNOVO0000000000000000001']
        kb = db.session.get(KnowledgeBase, imp.kb_id)
        check('impugnação na Base', kb is not None and kb.category == lote.CATEGORIA_BASE and kb.file_type == 'PDF',
              str(kb and (kb.category, kb.file_type)))
        check('… com processo pela regra (não o precedente)', kb.lawsuit_number == '5004186-40.2026.4.04.7010',
              str(kb.lawsuit_number))
        check('… com link do Drive e tipo de peça nas tags',
              'IDNOVO0000000000000000001' in (kb.source_url or '') and kb.tags == 'IMPUGNAÇÃO À CONTESTAÇÃO')
        check('… descrição no formato do lote', kb.description.startswith('Petição protocolada — IMPUGNAÇÃO À CONTESTAÇÃO')
              and 'TRF-4' in kb.description)
        check('… indexada (Qdrant/Meilisearch)', kb.id in indexados and kb.processing_status == 'completed')
        peca = db.session.get(ImpugnacaoReferenceModel, imp.peca_id) if imp.peca_id else None
        check('impugnação também vira peça-modelo, ligada ao id do Drive',
              peca is not None and peca.source_drive_file_id == 'IDNOVO0000000000000000001' and peca.file_type == 'pdf')

        ed = por_id['IDNOVO0000000000000000002']
        check('embargos: só Base, sem peça-modelo', ed.kb_id and not ed.peca_id)

        regs = {(r.drive_file_id, r.destination): r for r in DriveIngestion.query.filter_by(law_firm_id=firm.id)}
        r = regs.get(('IDNOVO0000000000000000001', svc.DESTINO_BASE))
        check('tela do Drive: registrada como importação automática',
              r and r.status == DriveIngestion.STATUS_ENVIADO and r.created_by_id is None and r.target_id == imp.kb_id)
        check('tela do Drive: peça-modelo também registrada', ('IDNOVO0000000000000000001', svc.DESTINO_PECA) in regs)
        r = regs.get(('IDLOTE000000000000000001', svc.DESTINO_BASE))
        check('veio pelo lote: registrado apontando para o existente, sem IA',
              r and r.target_id == do_lote.id and 'Contrarrazões - Lote _ PROTOCOLO.pdf' not in agente.chamadas)
        r = regs.get(('IDTESTE000000000000000001', svc.DESTINO_BASE))
        check('não é petição: não entra na base e fica com erro na tela',
              r and r.status == DriveIngestion.STATUS_ERRO and 'Escolha o destino' in r.error_message
              and not KnowledgeBase.query.filter_by(law_firm_id=firm.id, original_filename='TESTE - Documento fictício.pdf').count())
        r = regs.get(('IDSCAN0000000000000000001', svc.DESTINO_BASE))
        check('PDF escaneado: erro registrado (não tenta toda hora)', r and r.status == DriveIngestion.STATUS_ERRO)
        check('Drive fora do ar: nada registrado (tenta na próxima)',
              ('IDFORA0000000000000000001', svc.DESTINO_BASE) not in regs)

        print('\n3. Rodar de novo não duplica')
        chamadas_antes = len(agente.chamadas)
        kbs_antes = KnowledgeBase.query.filter_by(law_firm_id=firm.id).count()
        drive.falhar.clear()
        planos2 = svc.planejar(firm.id, drive=drive)
        a2 = {p.meta['id']: p.acao for p in planos2}
        check('já importados e já recusados: pular', all(a2[i] == svc.PULAR for i in (
            'IDNOVO0000000000000000001', 'IDLOTE000000000000000001', 'IDTESTE000000000000000001')))
        check('o que falhou por Drive fora volta a importar', a2['IDFORA0000000000000000001'] == svc.IMPORTAR)
        svc.executar(firm.id, planos2, drive=drive, agente=agente)
        check('só o que faltava foi lido', len(agente.chamadas) == chamadas_antes + 1, str(agente.chamadas[chamadas_antes:]))
        check('Base ganhou só 1 arquivo', KnowledgeBase.query.filter_by(law_firm_id=firm.id).count() == kbs_antes + 1)

        print('\n4. Indexação fora do ar (Qdrant parado): tenta de novo no mesmo registro')
        arquivos.append({'id': 'IDQDRANT00000000000000001', 'name': 'Qdrant fora _ PROTOCOLO.pdf', 'mimeType': 'application/pdf'})
        _pdf(os.path.join(pasta, 'IDQDRANT00000000000000001.pdf'), CORPO + 'qdrant')
        agente.fichas['Qdrant fora _ PROTOCOLO.pdf'] = {**FICHA, 'peca': 'APELAÇÃO'}

        def qdrant_fora(arquivo, dados):
            raise ConnectionRefusedError('[Errno 111] Connection refused')
        lote._ingerir_na_base = qdrant_fora
        svc.executar(firm.id, svc.planejar(firm.id, drive=drive), drive=drive, agente=agente)
        check('nada registrado na tela', not DriveIngestion.query.filter_by(
            law_firm_id=firm.id, drive_file_id='IDQDRANT00000000000000001').count())
        kb_falho = KnowledgeBase.query.filter(KnowledgeBase.law_firm_id == firm.id,
                                              KnowledgeBase.source_url.like('%IDQDRANT%')).one()
        check('registro da Base ficou com erro', kb_falho.processing_status == 'error')
        lote._ingerir_na_base = lambda arquivo, dados: indexados.append(arquivo.id) or 3
        planos3 = svc.planejar(firm.id, drive=drive)
        p3 = next(p for p in planos3 if p.meta['id'] == 'IDQDRANT00000000000000001')
        check('próxima rodada planeja retomar', p3.acao == svc.IMPORTAR and p3.kb_id == kb_falho.id)
        svc.executar(firm.id, planos3, drive=drive, agente=agente)
        db.session.expire_all()
        check('retomou o mesmo registro, sem duplicar',
              KnowledgeBase.query.filter(KnowledgeBase.law_firm_id == firm.id,
                                         KnowledgeBase.source_url.like('%IDQDRANT%')).count() == 1
              and db.session.get(KnowledgeBase, kb_falho.id).processing_status == 'completed')
        check('agora registrado na tela', DriveIngestion.query.filter_by(
            law_firm_id=firm.id, drive_file_id='IDQDRANT00000000000000001', target_id=kb_falho.id).count() == 1)

        print('\n5. Tela do Drive mostra "importação automática"')
        from app.services import drive_ingestion_service as telas
        sit = telas._situacoes(firm.id, [regs[('IDNOVO0000000000000000001', svc.DESTINO_BASE)]])
        check('quem = importação automática', list(sit.values())[0]['quem'] == 'importação automática')
    finally:
        lote._ingerir_na_base = orig_ing
        ref.ingest_reference = orig_ref
        shutil.rmtree(pasta, ignore_errors=True)
        db.session.rollback()
        _cleanup(firm)


def _cleanup(firm):
    for k in KnowledgeBase.query.filter_by(law_firm_id=firm.id).all():
        if k.file_path and k.file_path.startswith('uploads') and os.path.exists(k.file_path):
            os.remove(k.file_path)
    for p in ImpugnacaoReferenceModel.query.filter_by(law_firm_id=firm.id).all():
        if p.file_path and os.path.exists(p.file_path):
            os.remove(p.file_path)
    DriveIngestion.query.filter_by(law_firm_id=firm.id).delete()
    ImpugnacaoReferenceModel.query.filter_by(law_firm_id=firm.id).delete()
    KnowledgeBase.query.filter_by(law_firm_id=firm.id).delete()
    for u in User.query.filter_by(law_firm_id=firm.id).all():
        UserPageVisit.query.filter_by(user_id=u.id).delete()
        db.session.delete(u)
    db.session.delete(firm)
    db.session.commit()


def main() -> int:
    with app.app_context():
        run()
    print('\n' + '=' * 62)
    if _falhas:
        print(f'❌ {len(_falhas)} verificação(ões) falharam:')
        for nome in _falhas:
            print(f'   - {nome}')
        return 1
    print('✅ Tudo verde')
    return 0


if __name__ == '__main__':
    sys.exit(main())
