"""Formatação de CNPJ (completo e raiz) e CPF para exibição.

Fonte única da máscara. Antes existia uma cópia privada no blueprint
``disputes_center`` — e foi justamente por ser privada que o gerador de
petições não a enxergou e passou anos escrevendo o CNPJ na peça exatamente
como havia sido digitado no cadastro (GER-01).

Não confundir com ``dou_alert_service.formatar_cnpj``: aquela recebe dígitos
já extraídos e normalizados do texto do Diário Oficial e é estrita de
propósito. A daqui recebe o que veio do cadastro, que é campo de texto livre.
"""

TAMANHO_CNPJ = 14


def apenas_digitos(valor) -> str:
    """Tudo que não for dígito sai. ``None`` vira string vazia."""
    return ''.join(ch for ch in (valor or '') if ch.isdigit())


def formatar_cnpj(valor) -> str:
    """``'19630496000105'`` → ``'19.630.496/0001-05'``.

    Devolve o valor como veio quando não dá para mascarar — cadastro
    incompleto, ``'Não informado'``, ou um CNPJ alfanumérico (regra que passa
    a valer a partir de 2026), em que mascarar por posição corromperia o dado.
    Formatar o que já está formatado devolve a mesma coisa.
    """
    digitos = apenas_digitos(valor)
    if len(digitos) != TAMANHO_CNPJ:
        return valor if valor else ''
    return f'{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:14]}'


# ── Identificadores que o portal FAP manda como número ──────────────────
# A API de procurações devolve CNPJ raiz e CPF como inteiro: 00.482.840
# chega como 482840. Depois disso, str() não tem como saber quantos zeros
# faltam — só o tamanho do documento sabe (retorno da homologação de
# "Máscara de CNPJ no template", Painel FAP → Procurações).

TAMANHO_CNPJ_RAIZ = 8
TAMANHO_CPF = 11


def completar_zeros(valor, tamanho: int) -> str | None:
    """Só os dígitos, completados com zero à esquerda até ``tamanho``.

    ``None`` e vazio viram ``None``, para a coluna continuar nula. Mais dígitos
    do que o tamanho não é zero faltando, é outro dado: volta como veio, sem
    corte — cortar inventaria um documento que não existe.
    """
    digitos = apenas_digitos(None if valor is None else str(valor))
    if not digitos:
        return None
    if len(digitos) > tamanho:
        return digitos
    return digitos.zfill(tamanho)


def formatar_cnpj_raiz(valor) -> str:
    """``482840`` → ``'00.482.840'``. O que não cabe em 8 dígitos volta como veio."""
    digitos = completar_zeros(valor, TAMANHO_CNPJ_RAIZ)
    if digitos is None:
        return ''
    if len(digitos) != TAMANHO_CNPJ_RAIZ:
        return str(valor)
    return f'{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}'


def formatar_cpf(valor) -> str:
    """``7488971`` → ``'000.074.889-71'``. O que não cabe em 11 dígitos volta como veio."""
    digitos = completar_zeros(valor, TAMANHO_CPF)
    if digitos is None:
        return ''
    if len(digitos) != TAMANHO_CPF:
        return str(valor)
    return f'{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:11]}'


def raiz_contestacao_fap(item: dict, fallback_raiz=None) -> str:
    """Raiz (8 dígitos) de uma contestação vinda do portal FAP.

    O portal manda ``cnpj`` e ``cnpjRaiz`` como número, então 07.718.633/0081-63
    chega como ``7718633008163``. Os 8 primeiros dígitos disso são ``77186330``
    — foi assim que as contestações da UNIDASUL sumiram do filtro por raiz
    (E01 da Remessa R09). Ordem de confiança:

    1. ``cnpjRaiz``, o campo canônico, com os zeros devolvidos;
    2. ``cnpj`` completado para 14 antes de cortar;
    3. a raiz da empresa consultada — vigências antigas não trazem ``cnpj``.
    """
    raiz = completar_zeros(item.get('cnpjRaiz'), TAMANHO_CNPJ_RAIZ)
    if raiz and len(raiz) == TAMANHO_CNPJ_RAIZ:
        return raiz
    # Até 8 dígitos o "cnpj" já é uma raiz: completá-lo para 14 daria "00000079".
    cnpj = completar_zeros(item.get('cnpj'), TAMANHO_CNPJ)
    if cnpj and len(cnpj) == TAMANHO_CNPJ and len(cnpj.lstrip('0')) > TAMANHO_CNPJ_RAIZ:
        return cnpj[:TAMANHO_CNPJ_RAIZ]
    return completar_zeros(fallback_raiz, TAMANHO_CNPJ_RAIZ) or ''


def cpf_valido(valor) -> bool:
    """Dígitos verificadores do CPF (mod 11). Repetidos ("111.111.111-11") não valem."""
    digitos = completar_zeros(valor, TAMANHO_CPF)
    if not digitos or len(digitos) != TAMANHO_CPF or len(set(digitos)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(int(d) * peso for d, peso in zip(digitos[:tamanho], range(tamanho + 1, 1, -1)))
        dv = (soma * 10) % 11 % 10
        if dv != int(digitos[tamanho]):
            return False
    return True


# A página da Receita aceita CPF e nascimento pela URL e abre com os campos
# preenchidos (conferido em 21/10/2026); o captcha continua com a pessoa.
# É de lá que sai o nome do segurado, que nem o relatório nem a Consulta do
# FAP trazem.
URL_CONSULTA_CPF_RECEITA = (
    'https://servicos.receita.fazenda.gov.br/Servicos/CPF/ConsultaSituacao/ConsultaPublica.asp'
)


def link_consulta_cpf_receita(cpf, nascimento) -> str | None:
    """Link da situação cadastral do CPF na Receita, já preenchido.

    ``nascimento`` aceita ``date``/``datetime``, ``'dd/mm/aaaa'`` ou ISO.
    Sem um dos dois, ou com CPF de DV inválido, devolve ``None`` — a página
    recusaria a consulta e o link só faria a pessoa perder o captcha.
    """
    from datetime import date, datetime

    if not cpf_valido(cpf) or not nascimento:
        return None
    if isinstance(nascimento, datetime):
        nascimento = nascimento.date()
    if not isinstance(nascimento, date):
        texto = str(nascimento).strip()[:10]
        for formato in ('%d/%m/%Y', '%Y-%m-%d'):
            try:
                nascimento = datetime.strptime(texto, formato).date()
                break
            except ValueError:
                continue
        else:
            return None
    return (f'{URL_CONSULTA_CPF_RECEITA}?CPF={completar_zeros(cpf, TAMANHO_CPF)}'
            f'&NASCIMENTO={nascimento:%d%m%Y}')
