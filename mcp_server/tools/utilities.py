"""
Tools: Utilidades — consulta de CNPJ (OpenCNPJ)
"""
from __future__ import annotations


def consultar_cnpj_handler(cnpj: str) -> dict:
    """Consulta dados cadastrais de um CNPJ na OpenCNPJ (dados públicos da Receita)."""
    from app.services.open_cnpj_service import OpenCNPJService

    service = OpenCNPJService()
    result = service.lookup_company(cnpj)

    if not result.get("success"):
        return {
            "erro": result.get("message") or "CNPJ não encontrado na base pública.",
            "status_code": result.get("status_code"),
        }

    data = result.get("data") or {}
    digits = service.sanitize_cnpj(cnpj)
    if len(digits) == 14:
        data.setdefault("cnpj_consultado", service.format_cnpj(digits))
        sufixo = digits[8:12]
        data.setdefault("tipo_estabelecimento", "Matriz" if sufixo == "0001" else "Filial")
    return data
