"""Verificação do versionamento de prompts/referências do Revisor FAP.

Script standalone: exercita numeração max+1, salvar-e-ativar, change_note,
diff entre versões e snapshot de versões usadas (collect_active_versions).

Uso: uv run python tests/test_fap_review_settings_versioning.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, User, FapReviewPromptVersion
from app.services.fap_review_service import collect_active_versions


def run():
    with app.app_context():
        user = (User.query.filter_by(role='admin').first() or User.query.first())
        assert user is not None, 'Nenhum usuário no banco de dev'
        law_firm_id = user.law_firm_id

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['law_firm_id'] = user.law_firm_id

        # Garante que existe um prompt editável (cria versão inicial se preciso)
        resp = client.get('/fap-review/settings/prompts/type/revisor_rules/edit')
        assert resp.status_code == 302, f'HTTP {resp.status_code}'
        prompt = FapReviewPromptVersion.query.filter_by(
            law_firm_id=law_firm_id, prompt_type='revisor_rules',
        ).order_by(FapReviewPromptVersion.version_number.desc()).first()
        assert prompt is not None

        base_url = f'/fap-review/settings/prompts/{prompt.id}'

        # 1) Dois saves seguidos a partir da MESMA página → números distintos
        r1 = client.post(base_url, json={'content': 'conteudo A', 'change_note': 'nota A'})
        r2 = client.post(base_url, json={'content': 'conteudo B'})
        assert r1.status_code == 200 and r2.status_code == 200, (r1.status_code, r2.status_code)
        v1 = db.session.get(FapReviewPromptVersion, r1.get_json()['version_id'])
        v2 = db.session.get(FapReviewPromptVersion, r2.get_json()['version_id'])
        assert v2.version_number == v1.version_number + 1, \
            f'Numeração duplicada: v{v1.version_number} / v{v2.version_number}'
        assert v1.change_note == 'nota A', v1.change_note
        assert not v1.is_active and not v2.is_active, 'Rascunho não deveria ativar'

        # 2) Salvar e ativar → nova versão já ativa, anteriores desativadas
        r3 = client.post(base_url, json={'content': 'conteudo C', 'activate': True,
                                         'change_note': 'ativada direto'})
        assert r3.status_code == 200
        v3 = db.session.get(FapReviewPromptVersion, r3.get_json()['version_id'])
        assert v3.is_active, 'Salvar e Ativar não ativou'
        actives = FapReviewPromptVersion.query.filter_by(
            law_firm_id=law_firm_id, prompt_type='revisor_rules', is_active=True).count()
        assert actives == 1, f'{actives} versões ativas simultâneas'
        assert 'redirect_url' in r3.get_json()

        # 3) GET de versão inativa NÃO redireciona mais (banner na tela)
        r4 = client.get(f'/fap-review/settings/prompts/{v1.id}')
        assert r4.status_code == 200, f'HTTP {r4.status_code} (esperado 200 sem redirect)'
        assert 'inativa' in r4.get_data(as_text=True), 'Banner de versão inativa ausente'

        # 4) Diff entre versões
        r5 = client.get(f'/fap-review/settings/prompts/{v3.id}/diff/{v1.id}')
        assert r5.status_code == 200, f'HTTP {r5.status_code}'
        diff = r5.get_json()
        assert diff['success'] and any(l.startswith('+') for l in diff['lines']), diff

        # 5) Snapshot de versões ativas inclui o prompt recém-ativado
        versions = collect_active_versions(law_firm_id)
        assert versions.get('revisor_rules', {}).get('id') == v3.id, versions

        print('OK — numeração max+1, salvar-e-ativar, banner, diff e snapshot de versões')


if __name__ == '__main__':
    run()
