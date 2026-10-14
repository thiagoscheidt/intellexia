"""
Tela do Google Drive e envio dos arquivos às três bases.

Drive falso (nada de rede): confere que cada destino cria a linha certa na
base que já existe, que o mesmo destino não repete, que conteúdo idêntico
aponta para o que já existe, que falha não deixa nada na base de destino e que
só o escritório dono da conta vê a tela.

    uv run python tests/test_drive_ingestion.py
"""

import hashlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, DriveIngestion, ImpugnacaoReferenceModel, JurisprudenceUpload, KnowledgeBase, User
from app.services import drive_ingestion_service as svc
from app.services import google_drive_client as gdrive
from app.services import jurisprudence_upload_service

PREFIXO = 'testedrive'
PDF = b'%PDF-1.7\nconteudo de teste ' + os.urandom(16).hex().encode()
PDF_DECISAO = b'%PDF-1.7\ndecisao de teste ' + os.urandom(16).hex().encode()
DOCX = b'PK\x03\x04docx de teste ' + os.urandom(16).hex().encode()


def _arquivo(sufixo, nome, mime, conteudo):
    return {'id': f'{PREFIXO}{sufixo}', 'name': nome, 'mimeType': mime, 'size': str(len(conteudo)),
            'sharingUser': {'displayName': 'Daniella', 'emailAddress': 'daniella@exemplo.com.br'},
            'sharedWithMeTime': '2026-10-13T17:42:29.310Z', 'webViewLink': 'https://drive.google.com/x',
            '_conteudo': conteudo}


class DriveFalso:
    conta = 'teste@projeto.iam.gserviceaccount.com'

    def __init__(self, arquivos):
        self.arquivos = {a['id']: a for a in arquivos}

    def listar(self):
        return list(self.arquivos.values())

    def metadados(self, file_id):
        if file_id not in self.arquivos:
            raise gdrive.DriveSemAcesso('O arquivo não está compartilhado com a conta de serviço (ou foi removido).')
        return self.arquivos[file_id]

    def baixar(self, file_id, dest_dir, meta=None):
        meta = meta or self.metadados(file_id)
        os.makedirs(dest_dir, exist_ok=True)
        caminho = os.path.join(dest_dir, f'{file_id}.bin')
        with open(caminho, 'wb') as fh:
            fh.write(meta['_conteudo'])
        nome = meta['name'] + ('.pdf' if meta['mimeType'] in gdrive.EXPORTAVEIS else '')
        return caminho, nome, hashlib.sha256(meta['_conteudo']).hexdigest()


def _limpar(law_firm_id):
    caminhos = []
    regs = DriveIngestion.query.filter(DriveIngestion.drive_file_id.like(f'{PREFIXO}%')).all()
    for r in regs:
        modelo = {DriveIngestion.DEST_PECA_MODELO: ImpugnacaoReferenceModel,
                  DriveIngestion.DEST_DECISAO: JurisprudenceUpload,
                  DriveIngestion.DEST_BASE_CONHECIMENTO: KnowledgeBase}[r.destination]
        alvo = db.session.get(modelo, r.target_id) if r.target_id else None
        if alvo is not None:
            caminhos.append(alvo.file_path)
            db.session.delete(alvo)
        db.session.delete(r)
    db.session.commit()
    for c in caminhos:
        if c and os.path.exists(c):
            os.remove(c)


def _configurar(law_firm_id, chave):
    os.environ['GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE'] = chave
    os.environ['GOOGLE_DRIVE_LAW_FIRM_ID'] = str(law_firm_id)


def main():
    falhas = []
    antigo = dict(os.environ)
    disparar_original = jurisprudence_upload_service.disparar
    cliente_original = gdrive.cliente
    pecas_iniciadas = []
    with tempfile.NamedTemporaryFile(suffix='.json') as chave, app.app_context():
        admin = User.query.filter_by(role='admin').first()
        lf = admin.law_firm_id
        _limpar(lf)
        _configurar(lf, chave.name)
        jurisprudence_upload_service.disparar = lambda *a, **k: None   # sem IA no teste
        peca = _arquivo('peca', 'Impugnação Madife', gdrive.MIME_PDF, PDF)
        decisao = _arquivo('decisao', 'Sentença COAMO.pdf', gdrive.MIME_PDF, PDF_DECISAO)
        docx = _arquivo('docx', 'Minuta.docx', gdrive.MIME_DOCX, DOCX)
        mesmo = _arquivo('mesmo', 'Cópia da Madife.pdf', gdrive.MIME_PDF, PDF)   # mesmo conteúdo da peça
        imagem = _arquivo('img', 'foto.png', 'image/png', b'png')
        drive = DriveFalso([peca, decisao, docx, mesmo, imagem])
        iniciar = lambda lf_, ref_id: pecas_iniciadas.append(ref_id)

        def caso(nome, fn):
            try:
                fn()
                print(f'✓ {nome}')
            except Exception as e:
                db.session.rollback()
                falhas.append(nome)
                print(f'✗ {nome}: {type(e).__name__}: {e}')

        def configuracao():
            assert svc.situacao_da_configuracao(lf) == 'ok'
            assert svc.situacao_da_configuracao(lf + 999) == 'outro_escritorio'
            os.environ.pop('GOOGLE_DRIVE_LAW_FIRM_ID')
            assert svc.situacao_da_configuracao(lf) == 'sem_escritorio'
            os.environ['GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE'] = '/nao/existe.json'
            assert svc.situacao_da_configuracao(lf) == 'nao_configurado'
            _configurar(lf, chave.name)

        def peca_modelo():
            r = svc.ingerir(lf, [peca['id']], DriveIngestion.DEST_PECA_MODELO, admin.id, drive=drive, iniciar_peca=iniciar)
            assert r[0]['ok'], r
            ref = ImpugnacaoReferenceModel.query.filter_by(law_firm_id=lf, source_drive_file_id=peca['id']).one()
            assert ref.file_hash == hashlib.sha256(PDF).hexdigest()
            assert ref.original_filename == 'Impugnação Madife.pdf' and ref.file_type == 'pdf'
            assert os.path.exists(ref.file_path) and ref.ingestion_status == 'processing'
            assert pecas_iniciadas == [ref.id]
            reg = DriveIngestion.query.filter_by(drive_file_id=peca['id']).one()
            assert reg.status == 'enviado' and reg.target_id == ref.id
            # repetir o mesmo destino não cria outra peça
            r = svc.ingerir(lf, [peca['id']], DriveIngestion.DEST_PECA_MODELO, admin.id, drive=drive, iniciar_peca=iniciar)
            assert not r[0]['ok'] and 'Já enviado' in r[0]['mensagem'], r
            # mesmo conteúdo por outro arquivo aponta para a peça existente
            r = svc.ingerir(lf, [mesmo['id']], DriveIngestion.DEST_PECA_MODELO, admin.id, drive=drive, iniciar_peca=iniciar)
            assert r[0]['ok'] and 'Já existia' in r[0]['mensagem'], r
            assert DriveIngestion.query.filter_by(drive_file_id=mesmo['id']).one().target_id == ref.id
            assert ImpugnacaoReferenceModel.query.filter_by(law_firm_id=lf, file_hash=ref.file_hash).count() == 1
            assert pecas_iniciadas == [ref.id]

        def para_decisao():
            r = svc.ingerir(lf, [decisao['id']], DriveIngestion.DEST_DECISAO, admin.id, drive=drive)
            assert r[0]['ok'], r
            reg = DriveIngestion.query.filter_by(drive_file_id=decisao['id']).one()
            up = db.session.get(JurisprudenceUpload, reg.target_id)
            assert up.status == JurisprudenceUpload.STATUS_QUEUED and up.law_firm_id == lf
            assert open(up.file_path, 'rb').read() == PDF_DECISAO
            # DOCX não vai para a Jurisprudência
            r = svc.ingerir(lf, [docx['id']], DriveIngestion.DEST_DECISAO, admin.id, drive=drive)
            assert not r[0]['ok'] and 'só lê PDF' in r[0]['mensagem'], r

        def para_base_conhecimento():
            r = svc.ingerir(lf, [docx['id']], DriveIngestion.DEST_BASE_CONHECIMENTO, admin.id, drive=drive)
            assert r[0]['ok'], r
            reg = DriveIngestion.query.filter_by(drive_file_id=docx['id'],
                                                 destination=DriveIngestion.DEST_BASE_CONHECIMENTO).one()
            kb = db.session.get(KnowledgeBase, reg.target_id)
            assert kb.processing_status == 'pending' and kb.file_type == 'DOCX' and kb.user_id == admin.id
            assert 'Daniella' in kb.description and os.path.exists(kb.file_path)
            # o mesmo arquivo pode ir também para a peça-modelo (destino diferente)
            r = svc.ingerir(lf, [decisao['id']], DriveIngestion.DEST_BASE_CONHECIMENTO, admin.id, drive=drive)
            assert r[0]['ok'], r
            assert DriveIngestion.query.filter_by(drive_file_id=decisao['id']).count() == 2

        def falha_nao_grava_nada():
            antes = (ImpugnacaoReferenceModel.query.count(), KnowledgeBase.query.count())
            r = svc.ingerir(lf, [f'{PREFIXO}sumiu'], DriveIngestion.DEST_PECA_MODELO, admin.id, drive=drive, iniciar_peca=iniciar)
            assert not r[0]['ok'] and 'não está compartilhado' in r[0]['mensagem'], r
            r = svc.ingerir(lf, [imagem['id']], DriveIngestion.DEST_BASE_CONHECIMENTO, admin.id, drive=drive)
            assert not r[0]['ok'] and 'Tipo de arquivo' in r[0]['mensagem'], r
            assert (ImpugnacaoReferenceModel.query.count(), KnowledgeBase.query.count()) == antes
            reg = DriveIngestion.query.filter_by(drive_file_id=f'{PREFIXO}sumiu').one()
            assert reg.status == 'erro' and reg.target_id is None
            assert not os.listdir(os.path.join(svc.PASTA_TEMPORARIA, str(lf)))   # sem sobra de download
            # o escritório compartilha depois: tentar de novo funciona e reaproveita o registro
            drive.arquivos[f'{PREFIXO}sumiu'] = _arquivo('sumiu', 'Embargos.pdf', gdrive.MIME_PDF, b'%PDF-1.7 embargos ' + os.urandom(8))
            r = svc.tentar_de_novo(lf, reg.id, admin.id, drive=drive, iniciar_peca=iniciar)
            assert r['ok'], r
            assert DriveIngestion.query.filter_by(drive_file_id=f'{PREFIXO}sumiu').count() == 1
            assert svc.tentar_de_novo(lf + 999, reg.id, admin.id, drive=drive) is None   # outro escritório

        def painel():
            p = svc.painel(lf, drive=drive)
            assert p['estado'] == 'ok' and p['conta'] == DriveFalso.conta
            por_id = {a['id']: a for a in p['arquivos']}
            assert set(por_id) == set(drive.arquivos)
            motivos = {d['chave']: d['motivo'] for d in por_id[peca['id']]['destinos']}
            assert motivos[DriveIngestion.DEST_PECA_MODELO] == 'Já enviado para cá.'
            assert motivos[DriveIngestion.DEST_DECISAO] is None
            assert {d['chave']: d['motivo'] for d in por_id[docx['id']]['destinos']}[DriveIngestion.DEST_DECISAO]
            assert not por_id[peca['id']]['pendente'] and por_id[imagem['id']]['pendente']
            envio = por_id[peca['id']]['envios'][0]
            assert envio['situacao'] == 'processando' and envio['link'][0] == 'impugnacao_references.reference_detail'
            assert por_id[peca['id']]['compartilhado_por'] == 'Daniella'
            # a base marcou falha: a tela mostra a falha, não "enviado"
            ref = ImpugnacaoReferenceModel.query.filter_by(source_drive_file_id=peca['id']).one()
            ref.ingestion_status, ref.ingestion_error = 'failed', 'Docling caiu'
            db.session.commit()
            envio = {a['id']: a for a in svc.painel(lf, drive=drive)['arquivos']}[peca['id']]['envios'][0]
            assert envio['situacao'] == 'falhou' and envio['erro'] == 'Docling caiu'
            # arquivo que deixou de ser compartilhado continua na lista de órfãos
            del drive.arquivos[docx['id']]
            p = svc.painel(lf, drive=drive)
            assert docx['id'] in {o['id'] for o in p['orfaos']}
            drive.arquivos[docx['id']] = docx
            # Drive fora do ar: aviso, sem exceção
            class Fora(DriveFalso):
                def listar(self):
                    raise gdrive.DriveIndisponivel('O Google Drive está indisponível agora (HTTP 503).')
            p = svc.painel(lf, drive=Fora([]))
            assert p['estado'] == 'erro' and '503' in p['erro'] and p['orfaos'] == []

        def tela():
            gdrive.cliente = lambda: drive
            c = app.test_client()
            with c.session_transaction() as s:
                s['user_id'] = admin.id; s['law_firm_id'] = lf; s['user_role'] = 'admin'; s['user_name'] = admin.name
            html = c.get('/settings/google-drive').get_data(as_text=True)
            assert 'Impugnação Madife' in html and 'Sentença COAMO.pdf' in html, html[:500]
            assert 'Já enviado para cá.' in html and 'A Base de Jurisprudência só lê PDF.' in html
            resp = c.post('/settings/google-drive/ingerir', data={'file_ids': [mesmo['id']],
                                                                   'destino': DriveIngestion.DEST_DECISAO})
            assert resp.status_code == 302
            # outro escritório
            os.environ['GOOGLE_DRIVE_LAW_FIRM_ID'] = str(lf + 999)
            assert 'não configurada para este escritório' in c.get('/settings/google-drive').get_data(as_text=True)
            _configurar(lf, chave.name)
            # não-admin não entra (o middleware relê o papel do banco, então precisa ser outro usuário)
            comum = User.query.filter(User.law_firm_id == lf, User.role != 'admin', User.is_active.is_(True)).first()
            if comum is not None:
                with c.session_transaction() as s:
                    s['user_id'] = comum.id; s['user_role'] = comum.role; s['user_name'] = comum.name
                assert c.get('/settings/google-drive').status_code == 302
                assert c.post('/settings/google-drive/ingerir', data={
                    'file_ids': [imagem['id']], 'destino': DriveIngestion.DEST_PECA_MODELO}).status_code == 302
                assert DriveIngestion.query.filter_by(drive_file_id=imagem['id'],
                                                      destination=DriveIngestion.DEST_PECA_MODELO).count() == 0

        try:
            for nome, fn in (('configuração', configuracao), ('peça-modelo', peca_modelo),
                             ('decisão', para_decisao), ('base de conhecimento', para_base_conhecimento),
                             ('falha não grava nada', falha_nao_grava_nada), ('painel', painel), ('tela', tela)):
                caso(nome, fn)
        finally:
            jurisprudence_upload_service.disparar = disparar_original
            gdrive.cliente = cliente_original
            _limpar(lf)
            os.environ.clear()
            os.environ.update(antigo)

    print('\nOK' if not falhas else f'\n{len(falhas)} falha(s): {", ".join(falhas)}')
    sys.exit(1 if falhas else 0)


if __name__ == '__main__':
    main()
