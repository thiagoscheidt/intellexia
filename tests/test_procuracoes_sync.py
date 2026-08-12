#!/usr/bin/env python3
"""
Testes da sincronização de procurações FAP e das duas notificações.

Script standalone no padrão do projeto — não usa framework de testes. Não vai à
rede: alimenta o serviço com um dublê de ``FapWebService`` que devolve uma lista
de dicts no formato da API.

Trabalha num escritório descartável (``law_firms`` com nome fixo), criado e
removido no fim, para não sujar os dados do ambiente.

Executar:
    uv run python tests/test_procuracoes_sync.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from main import app
from app.models import (
    db, LawFirm, NotificationSetting,
    FapWebProcuracao, FapWebProcuracaoChangeHistory,
)
from app.services import fap_procuracoes_service as svc_mod
from app.services import notification_service
from app.services.fap_procuracoes_service import _utcnow

FIRM_NAME = '__TESTE_PROCURACOES__'

falhas = []


def check(condicao, descricao, detalhe=''):
    if condicao:
        print(f'  ✓ {descricao}')
    else:
        print(f'  ✗ {descricao}{(" — " + detalhe) if detalhe else ""}')
        falhas.append(descricao)


class FakeResult:
    def __init__(self, data, ok=True, message='', expired=False):
        self.ok = ok
        self.data = data
        self.message = message
        self.expired = expired


class FakeService:
    """Dublê de FapWebService: devolve a lista informada, sem rede."""

    def __init__(self, items, ok=True, message='', expired=False):
        self.items = items
        self.ok = ok
        self.message = message
        self.expired = expired

    def fetch_procuracoes(self):
        return FakeResult(self.items, ok=self.ok, message=self.message, expired=self.expired)


def procuracao(protocolo, situacao='DEFERIDA', data_fim='2027-01-01',
               nome='EMPRESA TESTE LTDA', cnpj_raiz='19630496',
               tipo='PROCURACAO_FAP', data_inicio='2025-01-01'):
    return {
        'protocolo': protocolo,
        'tipoProcuracao': {'codigo': tipo, 'descricao': 'Procuração FAP'},
        'situacao': {'codigo': situacao, 'descricao': situacao.capitalize()},
        'dataInicio': data_inicio,
        'dataFim': data_fim,
        'cnpjRaizOutorgante': int(cnpj_raiz),
        'nomeEmpresaOutorgante': nome,
        'cpfOutorgado': 12345678901,
        'cnpjRaizOutorgado': None,
        'dataCadastro': '2025-01-01T10:00:00Z',
    }


def historico(law_firm_id):
    return (FapWebProcuracaoChangeHistory.query
            .filter_by(law_firm_id=law_firm_id)
            .order_by(FapWebProcuracaoChangeHistory.id)
            .all())


def limpar(law_firm_id):
    FapWebProcuracaoChangeHistory.query.filter_by(law_firm_id=law_firm_id).delete()
    FapWebProcuracao.query.filter_by(law_firm_id=law_firm_id).delete()
    NotificationSetting.query.filter_by(law_firm_id=law_firm_id).delete()
    db.session.commit()


def teste_ingestao_inicial(fid):
    print('\n[1] Primeira ingestão')
    limpar(fid)
    stats = svc_mod.sync_procuracoes(FakeService([procuracao('P-1'), procuracao('P-2')]), fid)

    check(stats['ok'], 'sync devolve ok')
    check(stats['created'] == 2, 'duas criadas', f"created={stats['created']}")
    check(stats['updated'] == 0 and stats['unchanged'] == 0, 'nada atualizado nem inalterado')

    linhas = historico(fid)
    check(len(linhas) == 2, 'duas linhas de histórico', f'{len(linhas)}')
    check(all(l.change_type == 'created' for l in linhas), 'ambas como created')
    check(all(l.is_alertavel for l in linhas), 'ambas alertáveis')


def teste_reingestao_identica(fid):
    print('\n[2] Reingestão idêntica não gera histórico')
    antes = len(historico(fid))
    stats = svc_mod.sync_procuracoes(FakeService([procuracao('P-1'), procuracao('P-2')]), fid)

    check(stats['unchanged'] == 2, 'duas sem mudança', f"unchanged={stats['unchanged']}")
    check(stats['created'] == 0 and stats['updated'] == 0, 'nenhuma criada nem atualizada')
    check(len(historico(fid)) == antes, 'histórico não cresceu')


def teste_mudanca_de_situacao(fid):
    print('\n[3] Mudança de situação gera alerta')
    antes = len(historico(fid))
    stats = svc_mod.sync_procuracoes(
        FakeService([procuracao('P-1', situacao='EXCLUIDA'), procuracao('P-2')]), fid
    )

    check(stats['updated'] == 1, 'uma atualizada', f"updated={stats['updated']}")
    check(stats['alertaveis'] == 1, 'uma alertável', f"alertaveis={stats['alertaveis']}")

    novas = historico(fid)[antes:]
    check(len(novas) == 1, 'uma linha nova de histórico', f'{len(novas)}')
    linha = novas[0]
    check(linha.is_alertavel, 'marcada como alertável')
    check('situacao_codigo' in (linha.changed_fields or ''), 'situacao_codigo entre os campos alterados')

    alerta = svc_mod.build_procuracoes_alert(fid, since=_utcnow() - timedelta(minutes=5))
    check(alerta['totais']['alteradas'] == 1, 'alerta traz uma alterada')
    mudancas = alerta['alteradas'][0]['mudancas'] if alerta['alteradas'] else []
    de_para = [(m['campo'], m['de'], m['para']) for m in mudancas]
    check(('Situação', 'DEFERIDA', 'EXCLUIDA') in de_para,
          'de-para correto da situação', str(de_para))


def teste_mudanca_nao_alertavel(fid):
    print('\n[4] Mudança cadastral fica no histórico sem virar e-mail')
    # Compara antes/depois em vez de total absoluto: o DATETIME do MySQL trunca
    # os sub-segundos, e as etapas anteriores caem no mesmo segundo desta.
    janela = _utcnow() - timedelta(hours=1)
    alerta_antes = svc_mod.build_procuracoes_alert(fid, since=janela)['totais']['total']
    antes = len(historico(fid))

    stats = svc_mod.sync_procuracoes(
        FakeService([
            procuracao('P-1', situacao='EXCLUIDA'),
            procuracao('P-2', nome='EMPRESA TESTE S.A.'),
        ]),
        fid,
    )

    check(stats['updated'] == 1, 'uma atualizada', f"updated={stats['updated']}")
    check(stats['alertaveis'] == 0, 'nenhuma alertável', f"alertaveis={stats['alertaveis']}")

    novas = historico(fid)[antes:]
    check(len(novas) == 1, 'histórico registrou a mudança')
    check(novas and not novas[0].is_alertavel, 'gravada como não alertável')

    alerta_depois = svc_mod.build_procuracoes_alert(fid, since=janela)['totais']['total']
    check(alerta_depois == alerta_antes, 'alerta não ganhou item',
          f'{alerta_antes} → {alerta_depois}')


def teste_digest_faixas(fid):
    print('\n[5] Resumo diário: faixas, renovação e situação')
    limpar(fid)
    hoje = date.today()

    def iso(dias):
        return (hoje + timedelta(days=dias)).isoformat()

    items = [
        procuracao('V-VENCIDA',   data_fim=iso(-5),  cnpj_raiz='11111111'),
        procuracao('V-URGENTE',   data_fim=iso(3),   cnpj_raiz='22222222'),
        procuracao('V-JANELA',    data_fim=iso(20),  cnpj_raiz='33333333'),
        procuracao('V-LONGE',     data_fim=iso(120), cnpj_raiz='44444444'),
        procuracao('V-PENDENTE',  data_fim=iso(3),   cnpj_raiz='55555555', situacao='PENDENTE'),
        procuracao('V-ANTIGA',    data_fim=iso(-90), cnpj_raiz='66666666'),
        # Renovação: mesma raiz/tipo da vencida abaixo, com vigência posterior.
        procuracao('R-VELHA',     data_fim=iso(-2),  cnpj_raiz='77777777'),
        procuracao('R-NOVA',      data_fim=iso(300), cnpj_raiz='77777777'),
    ]
    svc_mod.sync_procuracoes(FakeService(items), fid)

    digest = svc_mod.build_procuracoes_digest(fid, since=_utcnow() - timedelta(minutes=5))
    protos = lambda bloco: {i['protocolo'] for i in digest[bloco]}

    check(protos('vencidas') == {'V-VENCIDA'}, 'bloco vencidas', str(protos('vencidas')))
    check(protos('vence_7') == {'V-URGENTE'}, 'bloco até 7 dias', str(protos('vence_7')))
    check(protos('vence_30') == {'V-JANELA'}, 'bloco 8 a 30 dias', str(protos('vence_30')))
    check('V-LONGE' not in protos('vence_30'), 'vencimento distante fica fora')
    check('V-PENDENTE' not in protos('vence_7'), 'PENDENTE não entra nos vencimentos')
    check('V-ANTIGA' not in protos('vencidas'), 'vencida há muito tempo sai da lista')
    check('R-VELHA' not in protos('vencidas'), 'vencida com renovação é suprimida')
    check(digest['totais']['novas'] == len(items), 'todas contam como novas no período',
          f"novas={digest['totais']['novas']}")
    check(digest['has_novidades'], 'has_novidades verdadeiro')

    # Sem novidade no período, mas com vencimento na janela: ainda deve enviar.
    futuro = _utcnow() + timedelta(minutes=5)
    digest2 = svc_mod.build_procuracoes_digest(fid, since=futuro)
    check(digest2['totais']['novas'] == 0, 'janela futura zera as novas')
    check(digest2['has_novidades'], 'vencimento sozinho ainda dispara o resumo')


def teste_alerta_fora_do_cron_horario(fid):
    print('\n[6] Alerta não é varrido pelo cron horário')
    setting = notification_service.get_or_create_setting(
        fid, NotificationSetting.TYPE_PROCURACOES_ALERT
    )
    setting.is_enabled = True
    setting.set_recipients(['teste@example.com'])
    setting.send_hour = 8
    setting.last_sent_at = None
    db.session.commit()

    from app.utils.timezone import SP_TZ
    agora = datetime.now(SP_TZ).replace(hour=8, minute=0)

    check(not notification_service.is_due(setting, now_sp=agora),
          'is_due falso mesmo no horário configurado')
    devidas = notification_service.due_settings(now_sp=agora)
    check(all(s.notification_type != NotificationSetting.TYPE_PROCURACOES_ALERT for s in devidas),
          'due_settings não devolve o alerta')
    check(NotificationSetting.TYPE_PROCURACOES_ALERT in notification_service.SENDERS,
          'mas o alerta tem enviador registrado')
    check(NotificationSetting.TYPE_PROCURACOES_DIGEST in notification_service.SENDERS,
          'e o resumo diário também')


def teste_falha_na_busca(fid):
    print('\n[7] Falha na busca não toca no banco')
    antes_proc = FapWebProcuracao.query.filter_by(law_firm_id=fid).count()
    antes_hist = len(historico(fid))

    stats = svc_mod.sync_procuracoes(
        FakeService([], ok=False, message='Sessão expirada', expired=True), fid
    )

    check(not stats['ok'], 'sync devolve ok=False')
    check(stats['expired'], 'sinaliza expired')
    check(FapWebProcuracao.query.filter_by(law_firm_id=fid).count() == antes_proc,
          'nenhuma procuração alterada')
    check(len(historico(fid)) == antes_hist, 'nenhuma linha de histórico')


def teste_render_dos_emails(fid):
    print('\n[8] E-mails renderizam')
    since = _utcnow() - timedelta(days=1)

    html_alerta, _ = notification_service.render_procuracoes_alert(fid, since=since, is_test=True)
    check('Procurações FAP' in html_alerta, 'alerta renderiza com o título')

    html_digest, digest = notification_service.render_procuracoes_digest(fid, since=since, is_test=True)
    check('Procurações FAP' in html_digest, 'resumo renderiza com o título')
    check('Vencem em até 7 dias' in html_digest or not digest['vence_7'],
          'bloco de urgência aparece quando há item')


def main():
    with app.app_context():
        firm = LawFirm.query.filter_by(name=FIRM_NAME).first()
        criado_aqui = firm is None
        if criado_aqui:
            firm = LawFirm(name=FIRM_NAME, cnpj='00000000000000')
            db.session.add(firm)
            db.session.commit()
        fid = firm.id

        try:
            teste_ingestao_inicial(fid)
            teste_reingestao_identica(fid)
            teste_mudanca_de_situacao(fid)
            teste_mudanca_nao_alertavel(fid)
            teste_digest_faixas(fid)
            teste_alerta_fora_do_cron_horario(fid)
            teste_falha_na_busca(fid)
            teste_render_dos_emails(fid)
        finally:
            limpar(fid)
            if criado_aqui:
                db.session.delete(db.session.get(LawFirm, fid))
                db.session.commit()

    print('\n' + '=' * 60)
    if falhas:
        print(f'{len(falhas)} verificação(ões) falharam:')
        for f in falhas:
            print(f'  - {f}')
        return 1
    print('Todas as verificações passaram.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
