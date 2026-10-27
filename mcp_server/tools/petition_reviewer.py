"""
Tools: Revisor de Petições FAP
==============================
A revisão pedida pelo Claude entra no módulo como a enviada pela tela: cria a
execução "processando" e roda o mesmo agente em segundo plano
(`fap_review._start_review_in_background`), com os prompts, referências,
pontos de atenção e achados descartados do escritório.

Rodar o agente dentro da chamada não funciona (RPI-37): em produção a revisão
passa de 5 minutos — o prompt carrega o manual FAP e os casos de referência, e
o raciocínio do modelo vai a dezenas de milhares de tokens — e o app do Claude
desiste antes. A tool responde na hora; o resultado sai por detalhar_revisao e
por e-mail a quem pediu.
"""
from __future__ import annotations

import os

_SEM_ID_WRIKE = (
    "Informe o Id Wrike da petição em 'identificador_documento'. Pergunte ao "
    "usuário qual é antes de chamar de novo — a revisão é registrada nessa petição."
)


def _abrir_revisao(law_firm_id: int, user_id: int | None, identificador: str | None,
                   abrir) -> dict:
    """Abre a revisão no módulo e dispara o agente em segundo plano.

    ``abrir()`` devolve o dicionário de `open_file_review` — muda só de onde o
    arquivo vem (texto gravado em .txt, arquivo baixado do Drive).
    """
    from app.blueprints.fap_review import _start_review_in_background
    from app.services.fap_review_service import revision_result_url
    from app.services.fap_review_upload_service import pergunta_claude

    try:
        aberta = abrir()
    except ValueError as e:
        return {"erro": str(e)}

    revisao_id = aberta["revisao_id"]
    numero = aberta["numero_revisao"]
    link = revision_result_url(revisao_id)
    if aberta["ja_em_andamento"]:
        inicio = (f"A petição \"{aberta['titulo']}\" já tem a revisão {numero} em andamento, "
                  "então não abri outra.")
    else:
        inicio = (f"Revisão {numero} da petição \"{aberta['titulo']}\" iniciada. "
                  "Ela leva alguns minutos e roda no IntellexIA — você não precisa ficar aqui esperando.")
    pergunta = pergunta_claude(numero, str(identificador).strip())
    resposta = {
        "status": "processando",
        "ja_em_andamento": aberta["ja_em_andamento"],
        "peticao_id": aberta["peticao_id"],
        "peticao_criada": aberta["peticao_criada"],
        "titulo": aberta["titulo"],
        "revisao_id": revisao_id,
        "numero_revisao": numero,
        "link": link,
        # O Claude repassa isto: sem o texto pronto, ele tende a omitir o link
        # ou a dizer que vai "aguardar" — e não há como aguardar daqui.
        "mensagem_para_usuario": (
            f"{inicio} Acompanhe por este link: {link}. Quando terminar, você recebe "
            f"um e-mail; ou me pergunte \"{pergunta}\" que eu trago os achados."
        ),
        "proximo_passo": (
            "Repasse a 'mensagem_para_usuario' ao usuário, com o link, e encerre a "
            "resposta. Não espere, não chame esta ferramenta de novo e não consulte "
            "o resultado agora: ele ainda não existe. Quando o usuário perguntar, use "
            f"detalhar_revisao(revisao_id={revisao_id})."
        ),
    }
    if aberta["ja_em_andamento"]:
        return resposta

    _start_review_in_background(
        revisao_id, law_firm_id, aberta["petition_path"], aberta["compared_path"],
        notify_user=True,
    )
    return resposta


def _preparar(identificador: str | None) -> dict | None:
    """Recusas comuns a toda entrada; None quando dá para seguir."""
    if not (identificador or "").strip():
        return {"erro": _SEM_ID_WRIKE}
    if not os.getenv("OPENAI_API_KEY"):
        return {"erro": "OPENAI_API_KEY não configurada no servidor."}
    return None


def _link_de_envio(law_firm_id: int, user_id: int | None, identificador: str, titulo: str) -> dict:
    """Sem texto nem Drive: link de uso único para o arquivo chegar (página ou curl)."""
    from app.services.fap_review_upload_service import (
        create_upload_link, expires_at_sp, upload_link_url,
    )

    try:
        link, token = create_upload_link(law_firm_id, user_id, identificador, titulo)
    except ValueError as e:
        return {"erro": str(e)}
    url = upload_link_url(token)
    expira = f"{expires_at_sp(link):%H:%M}"
    return {
        "status": "aguardando_arquivo",
        "link_envio": url,
        "expira_em": expira,
        "comando_curl": f'curl -sS -F arquivo=@"<caminho do anexo>" {url}',
        "mensagem_para_usuario": (
            f"Para eu mandar a petição para revisão, solte o arquivo (PDF, DOCX ou TXT) "
            f"nesta página: {url} — o link vale até {expira} e serve para um envio."
        ),
        "proximo_passo": (
            "Se o usuário anexou a petição nesta conversa: liste /mnt/user-data/attachments/ "
            "(ls -la) e considere só PDF, DOCX e TXT. Nenhum → não rode o curl; peça o "
            "arquivo ou repasse a 'mensagem_para_usuario'. Um → rode o 'comando_curl' com o "
            "caminho dele e repasse ao usuário a 'mensagem' do JSON devolvido, dizendo o "
            "nome do arquivo enviado. Mais de um → pergunte ao usuário qual é a petição, "
            "listando os nomes, antes de enviar (a menos que ele já tenha dito). Se o curl "
            "falhar (rede recusada, comando indisponível) ou não houver anexo, repasse a "
            "'mensagem_para_usuario' com o link e encerre."
        ),
    }


def _revisao_do_drive(law_firm_id: int, user_id: int | None, identificador: str,
                      titulo: str, link_drive: str) -> dict:
    """Baixa a petição do Drive e abre a revisão com o arquivo original."""
    from pathlib import Path

    from app.services import fap_review_service as svc
    from app.services.fap_review_upload_service import download_review_file_from_drive

    def abrir():
        # Antes de baixar: não baixa à toa o que a tela recusaria ou o que já roda.
        petition, _ = svc.check_new_revision_allowed(law_firm_id, identificador)
        running = svc.running_revision(petition)
        if running:
            return svc._in_progress_payload(petition, running)
        caminho, nome = download_review_file_from_drive(link_drive, law_firm_id)
        aberta = svc.open_file_review(law_firm_id, user_id, identificador, caminho, nome, title=titulo)
        if aberta["ja_em_andamento"]:
            Path(caminho).unlink(missing_ok=True)
        return aberta

    return _abrir_revisao(law_firm_id, user_id, identificador, abrir)


def compare_petition_versions_handler(
    texto_original: str,
    texto_revisado: str,
    law_firm_id: int,
    user_id: int | None = None,
    identificador_documento: str | None = None,
    titulo: str = "",
) -> dict:
    """Revisão comparativa (versão original × revisada) com o agente do escritório.

    Responde "a v2 corrigiu o que o revisor apontou?" com o próprio agente, em vez
    de o assistente comparar os textos por conta.
    """
    texto_original = (texto_original or "").strip()
    texto_revisado = (texto_revisado or "").strip()
    if len(texto_original) < 200 or len(texto_revisado) < 200:
        return {
            "erro": "Envie o texto completo das duas versões (mínimo ~200 caracteres cada)."
        }
    from app.services.fap_review_service import start_text_review

    recusa = _preparar(identificador_documento)
    if recusa:
        return recusa
    return _abrir_revisao(law_firm_id, user_id, identificador_documento, lambda: start_text_review(
        law_firm_id, user_id, identificador_documento, texto_original,
        title=titulo, compared_text=texto_revisado,
    ))


def review_petition_handler(
    petition_text: str | None,
    law_firm_id: int,
    user_id: int | None = None,
    identificador_documento: str | None = None,
    titulo: str = "",
    link_drive: str | None = None,
) -> dict:
    """Abre a revisão de uma petição no módulo Revisor, pelo Id Wrike.

    Texto → revisão do texto. Link do Drive → baixa e revisa o arquivo. Nenhum
    dos dois → link de envio de uso único (página ou curl do Claude).
    """
    from app.services.fap_review_service import start_text_review

    recusa = _preparar(identificador_documento)
    if recusa:
        return recusa
    petition_text = (petition_text or "").strip()
    link_drive = (link_drive or "").strip()
    if petition_text and link_drive:
        return {"erro": "Mande o texto ou o link do Drive, não os dois."}
    if link_drive:
        return _revisao_do_drive(law_firm_id, user_id, identificador_documento, titulo, link_drive)
    if not petition_text:
        return _link_de_envio(law_firm_id, user_id, identificador_documento, titulo)
    if len(petition_text) < 200:
        return {
            "erro": "Texto da petição muito curto para revisão (mínimo ~200 caracteres). "
                    "Envie o texto completo da petição, ou deixe o texto em branco para "
                    "receber o link de envio do arquivo."
        }
    return _abrir_revisao(law_firm_id, user_id, identificador_documento, lambda: start_text_review(
        law_firm_id, user_id, identificador_documento, petition_text, title=titulo,
    ))
