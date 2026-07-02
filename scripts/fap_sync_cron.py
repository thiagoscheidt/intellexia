#!/usr/bin/env python3
"""
Sincronização automática do Painel FAP — script para rodar via cron.

Sequência de execução:
  1. Verifica sessão FAP (aborta se expirada)
  2. Sincroniza empresas (upsert FapCompany)
  3. Sincroniza procurações (upsert FapWebProcuracao)
  4. Contestações — Fase 1: busca em paralelo (várias empresas ao mesmo tempo)
                   Fase 2: grava no banco sequencialmente (upsert FapWebContestacao)
  5. Download — fila única global: baixa em paralelo todos os PDFs sem arquivo local
                (pula os que já existem em disco)

Variáveis de ambiente (.env):
  FAP_AUTH_JSON        — JSON de autenticação (obrigatório)
                         Formato: { "cookies": { "SESSION": "...", "XSRF-TOKEN": "...", "ROUTEID": "..." },
                                    "userAgent": "Mozilla/5.0 ..." }
  FAP_SYNC_LAW_FIRM_ID — ID do escritório a sincronizar (padrão: 1)
  FAP_SYNC_YEARS       — Anos específicos separados por vírgula (sobrepõe o intervalo padrão)
                         Exemplo: 2026,2025,2024
  FAP_SYNC_START_YEAR  — Ano inicial do intervalo padrão (padrão: 2010 → busca de 2010 ao ano atual)
  FAP_SYNC_FETCH_WORKERS    — Nº de buscas de contestações em paralelo (padrão: 8, máx: 20)
  FAP_SYNC_DOWNLOAD    — '1' (padrão) baixa os PDFs após a sincronização; '0' desativa
  FAP_SYNC_DOWNLOAD_WORKERS — Nº de downloads em paralelo (fila global) (padrão: 8, máx: 30)

Execução manual:
  uv run python scripts/fap_sync_cron.py

Cron sugerido (diário às 6h):
  0 6 * * * cd /sites/intellexia && uv run python scripts/fap_sync_cron.py >> /var/log/intellexia/fap_sync.log 2>&1
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

# Garante que o projeto raiz esteja no path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Carrega .env antes de importar o app
from dotenv import load_dotenv  # type: ignore[import]
load_dotenv(project_root / '.env')


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


# Ano inicial padrão da sincronização (vai deste ano até o ano atual).
FAP_SYNC_START_YEAR = 2010


def _get_sync_years() -> list[int]:
    raw = os.environ.get('FAP_SYNC_YEARS', '').strip()
    if raw:
        try:
            return [int(y.strip()) for y in raw.split(',') if y.strip()]
        except ValueError:
            _log(f"AVISO: FAP_SYNC_YEARS inválido ('{raw}'). Usando padrão.")

    start = FAP_SYNC_START_YEAR
    raw_start = os.environ.get('FAP_SYNC_START_YEAR', '').strip()
    if raw_start:
        try:
            start = int(raw_start)
        except ValueError:
            _log(f"AVISO: FAP_SYNC_START_YEAR inválido ('{raw_start}'). Usando {FAP_SYNC_START_YEAR}.")

    current = datetime.now().year
    # Do ano atual para trás, até o ano inicial (ex.: 2026, 2025, ..., 2010).
    return list(range(current, start - 1, -1))


def _download_enabled() -> bool:
    raw = os.environ.get('FAP_SYNC_DOWNLOAD', '1').strip().lower()
    return raw not in ('0', 'false', 'no', 'nao', 'off', '')


def _download_workers() -> int:
    raw = os.environ.get('FAP_SYNC_DOWNLOAD_WORKERS', '').strip()
    if raw:
        try:
            return max(1, min(int(raw), 30))
        except ValueError:
            _log(f"AVISO: FAP_SYNC_DOWNLOAD_WORKERS inválido ('{raw}'). Usando padrão (8).")
    return 8


def _fetch_workers() -> int:
    raw = os.environ.get('FAP_SYNC_FETCH_WORKERS', '').strip()
    if raw:
        try:
            return max(1, min(int(raw), 20))
        except ValueError:
            _log(f"AVISO: FAP_SYNC_FETCH_WORKERS inválido ('{raw}'). Usando padrão (8).")
    return 8


def _get_law_firm_id(db, LawFirm) -> int:
    raw = os.environ.get('FAP_SYNC_LAW_FIRM_ID', '').strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    firm = LawFirm.query.filter_by(is_active=True).order_by(LawFirm.id).first()
    if not firm:
        raise RuntimeError("Nenhum escritório ativo encontrado no banco.")
    return firm.id


# ---------------------------------------------------------------------------
# Sync de empresas
# ---------------------------------------------------------------------------

def sync_companies(svc, db, FapCompany, law_firm_id: int) -> int:
    _log("  → Buscando empresas no portal FAP...")
    result = svc.fetch_companies()
    if not result.ok:
        _log(f"  ✗ Falha ao buscar empresas: {result.message}")
        return 0

    companies = result.data if isinstance(result.data, list) else []
    now = datetime.now()
    seen_cnpjs: set[str] = set()

    for item in companies:
        cnpj = str(item.get('cnpj') or '').strip()
        if not cnpj:
            continue
        seen_cnpjs.add(cnpj)
        tipo = item.get('tipoProcuracao') or {}
        nome = (item.get('nome') or '').strip()
        rec = FapCompany.query.filter_by(law_firm_id=law_firm_id, cnpj=cnpj).first()
        if rec:
            rec.nome = nome
            rec.tipo_procuracao_codigo = tipo.get('codigo')
            rec.tipo_procuracao_descricao = tipo.get('descricao')
            rec.synced_at = now
        else:
            db.session.add(FapCompany(
                law_firm_id=law_firm_id,
                cnpj=cnpj,
                nome=nome,
                tipo_procuracao_codigo=tipo.get('codigo'),
                tipo_procuracao_descricao=tipo.get('descricao'),
                synced_at=now,
            ))

    # Poda empresas que não vieram mais na procuração — MAS preserva as que
    # têm contestações vinculadas (FK em fap_web_contestacoes.fap_company_id),
    # senão o DELETE falha por constraint e perderíamos histórico.
    removed = 0
    if seen_cnpjs:
        from app.models import FapWebContestacao
        stale = FapCompany.query.filter(
            FapCompany.law_firm_id == law_firm_id,
            FapCompany.cnpj.notin_(seen_cnpjs),
        ).all()
        for comp in stale:
            tem_contestacao = db.session.query(
                FapWebContestacao.id
            ).filter_by(
                law_firm_id=law_firm_id, fap_company_id=comp.id
            ).first()
            if tem_contestacao:
                continue  # mantém: empresa com histórico de contestações
            db.session.delete(comp)
            removed += 1

    db.session.commit()
    _log(f"  ✓ Empresas sincronizadas: {len(seen_cnpjs)} (removidas {removed} sem contestações)")
    return len(seen_cnpjs)


# ---------------------------------------------------------------------------
# Sync de procurações
# ---------------------------------------------------------------------------

def sync_procuracoes(svc, db, FapWebProcuracao, law_firm_id: int) -> dict:
    _log("  → Buscando procurações no portal FAP...")
    result = svc.fetch_procuracoes()
    if not result.ok:
        _log(f"  ✗ Falha ao buscar procurações: {result.message}")
        return {'created': 0, 'updated': 0}

    items = result.data if isinstance(result.data, list) else []
    now = datetime.now()
    created = 0
    updated = 0

    def _parse_date(s):
        if not s:
            return None
        try:
            return date.fromisoformat(s[:10])
        except Exception:
            return None

    def _parse_datetime(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace('Z', '+00:00').split('+')[0])
        except Exception:
            return None

    for item in items:
        protocolo = str(item.get('protocolo') or '').strip()
        if not protocolo:
            continue

        tipo = item.get('tipoProcuracao') or {}
        sit = item.get('situacao') or {}

        fields = dict(
            tipo_procuracao_codigo=tipo.get('codigo'),
            tipo_procuracao_descricao=tipo.get('descricao'),
            situacao_codigo=sit.get('codigo'),
            situacao_descricao=sit.get('descricao'),
            data_inicio=_parse_date(item.get('dataInicio')),
            data_fim=_parse_date(item.get('dataFim')),
            cnpj_raiz_outorgante=str(item['cnpjRaizOutorgante']) if item.get('cnpjRaizOutorgante') is not None else None,
            nome_empresa_outorgante=item.get('nomeEmpresaOutorgante'),
            cpf_outorgado=str(item['cpfOutorgado']) if item.get('cpfOutorgado') is not None else None,
            cnpj_raiz_outorgado=str(item['cnpjRaizOutorgado']) if item.get('cnpjRaizOutorgado') is not None else None,
            data_cadastro=_parse_datetime(item.get('dataCadastro')),
            raw_data=json.dumps(item, ensure_ascii=False),
            last_synced_at=now,
        )

        existing = FapWebProcuracao.query.filter_by(law_firm_id=law_firm_id, protocolo=protocolo).first()
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            updated += 1
        else:
            db.session.add(FapWebProcuracao(law_firm_id=law_firm_id, protocolo=protocolo, **fields))
            created += 1

    db.session.commit()
    _log(f"  ✓ Procurações: {created} criadas, {updated} atualizadas (total {len(items)})")
    return {'created': created, 'updated': updated}


# ---------------------------------------------------------------------------
# Sync de contestações (empresa × ano)
# ---------------------------------------------------------------------------

def fetch_contestacoes_for_company(auth, company_id: int, cnpj: str, years: list[int]) -> dict:
    """Apenas REDE: busca as contestações de uma empresa em todos os anos.

    Thread-safe (cria seu próprio FapWebService). Não toca no banco — devolve
    os itens crus para serem persistidos depois, no thread principal.

    Retorna {'company_id', 'years': {ano: [itens]}, 'expired': [anos], 'errors': [(ano, msg)]}.
    """
    from app.services.fap_web_service import FapWebService

    svc = FapWebService(auth)
    cnpj_digits = ''.join(ch for ch in str(cnpj or '') if ch.isdigit())
    cnpj_raiz = cnpj_digits[:8] if len(cnpj_digits) >= 8 else cnpj_digits

    out = {'company_id': company_id, 'years': {}, 'expired': [], 'errors': []}
    for year in years:
        result = svc.fetch_contestacoes(cnpj=cnpj_raiz, year=year)
        if not result.ok:
            if getattr(result, 'expired', False):
                out['expired'].append(int(year))
            else:
                out['errors'].append((int(year), result.message))
            continue
        out['years'][int(year)] = result.data if isinstance(result.data, list) else []
    return out


def persist_contestacoes_for_company(
    db,
    FapWebContestacao, FapWebContestacaoChangeHistory, FapAutoImportedContestacao,
    law_firm_id: int,
    company: object,
    fetched_years: dict,
) -> dict:
    """Persiste no banco (upsert + histórico) as contestações já buscadas.

    Roda no thread principal — escrita sequencial no banco.
    """
    cnpj_raw = str(company.cnpj or '').strip()
    cnpj_digits = ''.join(ch for ch in cnpj_raw if ch.isdigit())

    total_created = 0
    total_updated = 0

    tracked_fields = (
        'cnpj', 'cnpj_raiz', 'ano_vigencia', 'fap_company_id',
        'instancia_codigo', 'instancia_descricao',
        'situacao_codigo', 'situacao_descricao',
        'protocolo', 'data_transmissao', 'data_dou_date',
    )

    for year_int, items in fetched_years.items():
        now = datetime.now()
        created = 0
        updated = 0

        for item in items:
            cid = item.get('id')
            if not cid:
                continue

            cnpj_full = str(item.get('cnpj') or '').strip() or cnpj_digits[:8]
            cnpj_item_digits = ''.join(ch for ch in cnpj_full if ch.isdigit())
            cnpj_full_14 = cnpj_item_digits.zfill(14) if len(cnpj_item_digits) <= 14 else cnpj_item_digits
            # Raiz = primeiros 8 dígitos do CNPJ ORIGINAL (antes do zfill à esquerda).
            # Se derivada de cnpj_full_14, o padding desloca a raiz (ex.: "79894168" → "00000079").
            cnpj_raiz_item = cnpj_item_digits[:8]

            instancia = item.get('instancia') or {}
            situacao = item.get('situacao') or {}

            raw_dt = item.get('dataTransmissao')
            data_transmissao = None
            if raw_dt:
                try:
                    data_transmissao = datetime.fromisoformat(
                        raw_dt.replace('Z', '+00:00').split('+')[0]
                    )
                except Exception:
                    pass

            raw_dou = item.get('dataDOU')
            data_dou_date = None
            if raw_dou:
                try:
                    data_dou_date = datetime.fromisoformat(str(raw_dou)[:10]).date()
                except Exception:
                    pass

            # Dedup pela mesma chave única do banco
            # (uq_fap_web_contestacoes_law_firm_contestacao = law_firm_id + contestacao_id).
            # NÃO incluir cnpj_raiz aqui: o valor gravado na coluna pode divergir
            # do calculado agora (ex.: CNPJ zero-padded para 14 → raiz "00000079"),
            # fazendo a busca falhar e o INSERT violar a constraint (Duplicate entry).
            existing = FapWebContestacao.query.filter_by(
                law_firm_id=law_firm_id,
                contestacao_id=int(cid),
            ).first()

            next_values = {
                'cnpj': cnpj_full_14,
                'cnpj_raiz': cnpj_raiz_item,
                'ano_vigencia': year_int,
                'fap_company_id': company.id,
                'instancia_codigo': instancia.get('codigo'),
                'instancia_descricao': instancia.get('descricao'),
                'situacao_codigo': situacao.get('codigo'),
                'situacao_descricao': situacao.get('descricao'),
                'protocolo': item.get('protocolo'),
                'data_transmissao': data_transmissao,
                'data_dou_date': data_dou_date,
            }

            if existing:
                changed_old = {}
                changed_new = {}
                for field_name in tracked_fields:
                    curr = getattr(existing, field_name)
                    nxt = next_values[field_name]
                    if curr != nxt:
                        changed_old[field_name] = curr
                        changed_new[field_name] = nxt

                if changed_new:
                    db.session.add(FapWebContestacaoChangeHistory(
                        law_firm_id=law_firm_id,
                        contestacao_db_id=existing.id,
                        contestacao_id=existing.contestacao_id,
                        cnpj=cnpj_full_14,
                        cnpj_raiz=cnpj_raiz_item,
                        ano_vigencia=year_int,
                        change_type='updated',
                        changed_fields=json.dumps(sorted(changed_new.keys()), ensure_ascii=False),
                        old_values=json.dumps(changed_old, ensure_ascii=False, default=str),
                        new_values=json.dumps(changed_new, ensure_ascii=False, default=str),
                        synced_at=now,
                    ))

                    imported_link = FapAutoImportedContestacao.query.filter_by(
                        law_firm_id=law_firm_id,
                        contestacao_id=existing.contestacao_id,
                        cnpj=cnpj_full_14,
                    ).first()
                    if imported_link:
                        existing.needs_reprocess = True

                for k, v in next_values.items():
                    setattr(existing, k, v)
                existing.raw_data = json.dumps(item, ensure_ascii=False)
                existing.last_synced_at = now
                updated += 1
            else:
                rec = FapWebContestacao(
                    law_firm_id=law_firm_id,
                    contestacao_id=int(cid),
                    raw_data=json.dumps(item, ensure_ascii=False),
                    last_synced_at=now,
                    **next_values,
                )
                db.session.add(rec)
                db.session.flush()

                db.session.add(FapWebContestacaoChangeHistory(
                    law_firm_id=law_firm_id,
                    contestacao_db_id=rec.id,
                    contestacao_id=rec.contestacao_id,
                    cnpj=cnpj_full_14,
                    cnpj_raiz=cnpj_raiz_item,
                    ano_vigencia=year_int,
                    change_type='created',
                    changed_fields=json.dumps(sorted(next_values.keys()), ensure_ascii=False),
                    old_values='{}',
                    new_values=json.dumps(next_values, ensure_ascii=False, default=str),
                    synced_at=now,
                ))
                created += 1

        db.session.commit()
        _log(f"    Ano {year_int}: {len(items)} contestação(ões) — {created} criada(s), {updated} atualizada(s)")
        total_created += created
        total_updated += updated

    return {'created': total_created, 'updated': total_updated}


# ---------------------------------------------------------------------------
# Download dos PDFs das contestações (fila única global)
# ---------------------------------------------------------------------------

def download_pending_files(
    auth, db, FapWebContestacao,
    law_firm_id: int,
    years: list[int],
    max_workers: int = 5,
) -> dict:
    """Baixa, numa fila única, todos os PDFs sem arquivo local do escritório.

    Mais eficiente que baixar empresa-a-empresa: um só pool de workers cobre
    todas as empresas/anos de uma vez (sem ociosidade quando uma empresa tem
    poucos arquivos). Antes de ir à rede, resolve em disco os arquivos que já
    existem (não rebaixa) e salva em
    ``uploads/fap_web_contestacoes/{law_firm_id}/{ano}/{cnpj14}/``.
    """
    import os
    import glob
    from flask import current_app
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.services.fap_web_service import FapWebService

    year_ints = [int(y) for y in years]

    pending = (
        FapWebContestacao.query
        .filter(
            FapWebContestacao.law_firm_id == law_firm_id,
            FapWebContestacao.ano_vigencia.in_(year_ints),
            FapWebContestacao.file_path.is_(None),
        )
        .with_entities(
            FapWebContestacao.id,
            FapWebContestacao.contestacao_id,
            FapWebContestacao.cnpj,
            FapWebContestacao.ano_vigencia,
        )
        .all()
    )

    if not pending:
        return {'pending': 0, 'downloaded': 0, 'failed': 0, 'linked': 0, 'expired': False}

    upload_root = os.path.join(current_app.root_path, 'uploads', 'fap_web_contestacoes', str(law_firm_id))
    flask_app = current_app._get_current_object()

    # ── 1) Resolve arquivos que já existem em disco (não baixa de novo) ──
    # Cobre o caso de o PDF ter sido baixado antes mas o file_path ter ficado
    # nulo (ex.: run interrompido). Só vincula o caminho — sem ir à rede.
    to_download = []
    linked_from_disk = 0
    for rec in pending:
        save_dir = os.path.join(upload_root, str(rec.ano_vigencia), rec.cnpj)
        existing = next(
            (m for m in glob.glob(os.path.join(save_dir, f'{rec.contestacao_id}_*')) if os.path.isfile(m)),
            None,
        )
        if existing:
            rel_path = '/'.join([
                'uploads', 'fap_web_contestacoes',
                str(law_firm_id), str(rec.ano_vigencia), rec.cnpj, os.path.basename(existing),
            ])
            db_rec = db.session.get(FapWebContestacao, rec.id)
            if db_rec:
                db_rec.file_path = rel_path
            linked_from_disk += 1
        else:
            to_download.append(rec)

    if linked_from_disk:
        db.session.commit()

    _log(f"  {len(pending)} pendente(s): {linked_from_disk} já em disco, {len(to_download)} para baixar")

    if not to_download:
        return {'pending': len(pending), 'downloaded': 0, 'failed': 0,
                'linked': linked_from_disk, 'expired': False}

    def _download_one(rec):
        svc = FapWebService(auth)
        try:
            dl = svc.download_contestacao(
                year=rec.ano_vigencia,
                cnpj=rec.cnpj,
                contestacao_id=rec.contestacao_id,
            )
            if not dl.ok:
                return {'rec_id': rec.id, 'ok': False,
                        'expired': bool(getattr(dl, 'expired', False)), 'error': dl.message}

            pdf_bytes = dl.data['pdf_bytes']
            filename  = f"{rec.contestacao_id}_{dl.data['filename']}"
            save_dir  = os.path.join(upload_root, str(rec.ano_vigencia), rec.cnpj)
            os.makedirs(save_dir, exist_ok=True)

            with open(os.path.join(save_dir, filename), 'wb') as f:
                f.write(pdf_bytes)

            rel_path = '/'.join([
                'uploads', 'fap_web_contestacoes',
                str(law_firm_id), str(rec.ano_vigencia), rec.cnpj, filename,
            ])

            with flask_app.app_context():
                db_rec = db.session.get(FapWebContestacao, rec.id)
                if db_rec:
                    db_rec.file_path = rel_path
                    db.session.commit()

            return {'rec_id': rec.id, 'ok': True, 'filename': filename}
        except Exception as e:
            try:
                with flask_app.app_context():
                    db.session.rollback()
            except Exception:
                pass
            return {'rec_id': rec.id, 'ok': False, 'expired': False, 'error': str(e)}

    downloaded = 0
    failed = 0
    expired = False
    done = 0
    total_dl = len(to_download)
    workers = max(1, min(max_workers, total_dl))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_download_one, r): r for r in to_download}
        for fut in as_completed(futures):
            res = fut.result()
            done += 1
            if res.get('ok'):
                downloaded += 1
            else:
                failed += 1
                if res.get('expired'):
                    expired = True
            if done % 50 == 0 or done == total_dl:
                _log(f"  ... download {done}/{total_dl} (ok={downloaded}, falhas={failed})")

    return {'pending': len(pending), 'downloaded': downloaded, 'failed': failed,
            'linked': linked_from_disk, 'expired': expired}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _log("=" * 60)
    _log("Iniciando sincronização automática do Painel FAP")
    _log("=" * 60)

    # 1. Carrega autenticação
    auth_json = os.environ.get('FAP_AUTH_JSON', '').strip()
    if not auth_json:
        _log("ERRO: FAP_AUTH_JSON não encontrado no .env. Abortando.")
        sys.exit(1)

    from app.services.fap_web_service import FapWebAuthPayload, FapWebService
    try:
        auth = FapWebAuthPayload.from_json(auth_json)
    except Exception as e:
        _log(f"ERRO: FAP_AUTH_JSON inválido: {e}. Abortando.")
        sys.exit(1)

    svc = FapWebService(auth)

    # 2. Verifica sessão
    _log("Verificando sessão FAP...")
    check = svc.check_session()
    if not check.ok:
        if getattr(check, 'expired', False):
            _log("ERRO: Sessão FAP expirada. Atualize FAP_AUTH_JSON no .env e tente novamente.")
        else:
            _log(f"ERRO: Sessão FAP inválida: {check.message}")
        sys.exit(1)
    _log("✓ Sessão FAP ativa")

    # 3. Carrega app Flask
    from main import app
    from app.models import (
        db, LawFirm, FapCompany, FapWebContestacao,
        FapWebContestacaoChangeHistory, FapWebProcuracao,
        FapAutoImportedContestacao,
    )

    years = _get_sync_years()
    _log(f"Anos a sincronizar: {years}")

    download_enabled = _download_enabled()
    download_workers = _download_workers()
    _log(
        f"Download de PDFs: {'ativado' if download_enabled else 'desativado'}"
        + (f" ({download_workers} em paralelo)" if download_enabled else '')
    )

    with app.app_context():
        law_firm_id = _get_law_firm_id(db, LawFirm)
        _log(f"Escritório: ID {law_firm_id}")

        # 4. Sincroniza empresas
        _log("\n[1/3] Sincronizando empresas...")
        try:
            sync_companies(svc, db, FapCompany, law_firm_id)
        except Exception as e:
            _log(f"  ✗ Erro ao sincronizar empresas: {e}")
            db.session.rollback()

        # 5. Sincroniza procurações
        _log("\n[2/3] Sincronizando procurações...")
        try:
            sync_procuracoes(svc, db, FapWebProcuracao, law_firm_id)
        except Exception as e:
            _log(f"  ✗ Erro ao sincronizar procurações: {e}")
            db.session.rollback()

        # 6. Sincroniza contestações por empresa × ano
        _log("\n[3/3] Sincronizando contestações...")
        companies = (
            FapCompany.query
            .filter_by(law_firm_id=law_firm_id)
            .order_by(FapCompany.nome)
            .all()
        )

        if not companies:
            _log("  ! Nenhuma empresa cadastrada. Execute a sincronização de empresas primeiro.")
        else:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            total = len(companies)
            fetch_workers = _fetch_workers()
            _log(f"  {total} empresa(s) — buscando contestações em paralelo ({fetch_workers} simultâneas)...")

            # ── Fase 1: BUSCA paralela (somente rede, sem tocar no banco) ──
            # Extrai só os dados necessários para as threads (sem acessar ORM lá).
            company_meta = [(c.id, c.cnpj) for c in companies]
            fetched_by_company = {}
            expired_count = 0
            done = 0
            with ThreadPoolExecutor(max_workers=fetch_workers) as pool:
                futures = {
                    pool.submit(fetch_contestacoes_for_company, auth, cid, cnpj, years): cid
                    for (cid, cnpj) in company_meta
                }
                for fut in as_completed(futures):
                    cid = futures[fut]
                    done += 1
                    try:
                        res = fut.result()
                    except Exception as e:
                        _log(f"  [{done}/{total}] ✗ Erro ao buscar empresa id={cid}: {e}")
                        continue
                    fetched_by_company[cid] = res
                    if res['expired']:
                        expired_count += 1
                    if done % 25 == 0 or done == total:
                        _log(f"  ... {done}/{total} empresas buscadas")

            _log(f"  ✓ Busca concluída ({len(fetched_by_company)}/{total} empresas)")

            # Se houve 401/403, confirma se a sessão caiu de fato
            if expired_count:
                chk = svc.check_session()
                if not chk.ok and getattr(chk, 'expired', False):
                    _log(f"  ✗ Sessão FAP expirou durante a busca — {expired_count} empresa(s) "
                         "não consultadas. Atualize FAP_AUTH_JSON e rode de novo. "
                         "Persistindo o que já foi obtido...")
                else:
                    _log(f"  ! {expired_count} empresa(s) com acesso negado (sem procuração). "
                         "Sessão segue ativa — ignorando essas.")

            # ── Fase 2: GRAVAÇÃO sequencial no banco ──────────────────────
            total_created = 0
            total_updated = 0
            for i, company in enumerate(companies, 1):
                res = fetched_by_company.get(company.id)
                nome = (company.nome or company.cnpj or '').strip()
                _log(f"\n  [{i}/{total}] {nome} (CNPJ: {company.cnpj})")

                if not res:
                    _log("      ! não buscada (falha na fase de busca)")
                    continue
                for (yr, msg) in res.get('errors', []):
                    _log(f"      ! ano {yr}: {msg}")
                if res.get('expired'):
                    _log(f"      ! acesso negado (sem procuração) nos anos: {res['expired']}")
                if not res['years']:
                    continue

                try:
                    stats = persist_contestacoes_for_company(
                        db, FapWebContestacao, FapWebContestacaoChangeHistory,
                        FapAutoImportedContestacao, law_firm_id, company, res['years'],
                    )
                    total_created += stats['created']
                    total_updated += stats['updated']
                except Exception as e:
                    _log(f"  ✗ Erro ao gravar {nome}: {e}")
                    db.session.rollback()

            _log(f"\n  ✓ Contestações: {total_created} criadas, {total_updated} atualizadas no total")

            # ── Fase 3: DOWNLOAD global dos PDFs (fila única) ─────────────
            if download_enabled:
                _log(f"\n[Download] Baixando PDFs em paralelo ({download_workers} workers)...")
                try:
                    dl = download_pending_files(
                        auth, db, FapWebContestacao,
                        law_firm_id, years, max_workers=download_workers,
                    )
                    _log(
                        f"  ✓ Download: {dl['downloaded']} baixado(s), "
                        f"{dl['linked']} já em disco, "
                        f"{dl['failed']} sem PDF/falha (de {dl['pending']} pendente(s))"
                    )
                    if dl['expired']:
                        chk = svc.check_session()
                        if not chk.ok and getattr(chk, 'expired', False):
                            _log("  ✗ Sessão FAP expirada durante o download. "
                                 "Atualize FAP_AUTH_JSON no .env e rode novamente.")
                        else:
                            _log("  ! Alguns documentos retornaram acesso negado, "
                                 "mas a sessão segue ativa.")
                except Exception as e:
                    _log(f"  ✗ Erro no download: {e}")
                    db.session.rollback()

    _log("\n" + "=" * 60)
    _log("Sincronização concluída com sucesso")
    _log("=" * 60)


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        _log(f"\nERRO FATAL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
