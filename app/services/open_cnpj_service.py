from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from opencnpj import OpenCNPJ


class OpenCNPJService:
    """Service de integração com OpenCNPJ via SDK e fallback HTTP."""

    BASE_URL = "https://api.opencnpj.org"

    @staticmethod
    def sanitize_cnpj(cnpj: str) -> str:
        return "".join(ch for ch in (cnpj or "") if ch.isdigit())

    @staticmethod
    def format_cnpj(cnpj_limpo: str) -> str:
        return f"{cnpj_limpo[:2]}.{cnpj_limpo[2:5]}.{cnpj_limpo[5:8]}/{cnpj_limpo[8:12]}-{cnpj_limpo[12:14]}"

    def lookup_company(self, cnpj: str) -> Dict[str, Any]:
        """Busca empresa e retorna payload padronizado para uso em rota/UI.

        Retorno:
            {"success": bool, "status_code": int, "message": str|None, "data": dict|None}
        """
        cnpj_limpo = self.sanitize_cnpj(cnpj)
        if len(cnpj_limpo) != 14:
            return {
                "success": False,
                "status_code": 400,
                "message": "CNPJ inválido para consulta na OpenCNPJ.",
                "data": None,
            }

        cnpj_formatado = self.format_cnpj(cnpj_limpo)
        tentativas = [cnpj or "", cnpj_formatado, cnpj_limpo]

        sdk_fatal_message: Optional[str] = None

        # 1) SDK
        try:
            api = OpenCNPJ()
            for cnpj_teste in tentativas:
                cnpj_teste = (cnpj_teste or "").strip()
                if not cnpj_teste:
                    continue

                try:
                    empresa = api.find_by_cnpj(cnpj_teste)
                    if empresa:
                        return {
                            "success": True,
                            "status_code": 200,
                            "message": None,
                            "data": self._serialize_company(empresa),
                        }
                except Exception as sdk_error:
                    error_text = str(sdk_error)
                    if "status 404" in error_text or "not_found" in error_text:
                        continue
                    raise
        except Exception as sdk_fatal_error:
            sdk_fatal_message = str(sdk_fatal_error)

        # 2) Fallback HTTP
        try:
            for cnpj_teste in [cnpj_limpo, cnpj_formatado]:
                response = requests.get(f"{self.BASE_URL}/{cnpj_teste}", timeout=15)

                if response.status_code == 200:
                    payload = response.json() if response.content else {}
                    return {
                        "success": True,
                        "status_code": 200,
                        "message": None,
                        "data": self._serialize_company(payload),
                    }

                if response.status_code == 404:
                    continue

                return {
                    "success": False,
                    "status_code": 502,
                    "message": f"Erro ao consultar OpenCNPJ (HTTP {response.status_code}).",
                    "data": None,
                }
        except Exception as http_error:
            if sdk_fatal_message:
                return {
                    "success": False,
                    "status_code": 502,
                    "message": (
                        f"Falha SDK OpenCNPJ: {sdk_fatal_message} | "
                        f"Falha fallback HTTP: {str(http_error)}"
                    ),
                    "data": None,
                }
            return {
                "success": False,
                "status_code": 502,
                "message": f"Erro ao consultar OpenCNPJ: {str(http_error)}",
                "data": None,
            }

        return {
            "success": False,
            "status_code": 404,
            "message": "CNPJ não encontrado na OpenCNPJ.",
            "data": None,
        }

    def lookup_and_sync_client(self, client: Any, db_session: Any) -> Dict[str, Any]:
        """Consulta CNPJ e sincroniza o cadastro local do cliente quando houver sucesso."""
        result = self.lookup_company(getattr(client, "cnpj", ""))

        if not result.get("success"):
            return result

        data = result.get("data") or {}
        try:
            self._apply_company_data_to_client(client, data)
            db_session.commit()
            return result
        except Exception as sync_error:
            db_session.rollback()
            result["success"] = False
            result["status_code"] = 500
            result["message"] = f"Dados consultados, mas falha ao sincronizar cliente: {str(sync_error)}"
            return result

    @staticmethod
    def _apply_company_data_to_client(client: Any, data: Dict[str, Any]) -> None:
        # Mantém o CNPJ normalizado no padrão com máscara para consistência visual no sistema.
        cnpj_raw = (data.get("cnpj") or "").strip()
        cnpj_digits = "".join(ch for ch in cnpj_raw if ch.isdigit())

        if cnpj_digits and len(cnpj_digits) == 14:
            client.cnpj = f"{cnpj_digits[:2]}.{cnpj_digits[2:5]}.{cnpj_digits[5:8]}/{cnpj_digits[8:12]}-{cnpj_digits[12:14]}"

        client.name = data.get("razao_social") or client.name
        client.street = data.get("logradouro") or client.street
        client.number = data.get("numero") or client.number
        client.district = data.get("bairro") or client.district
        client.city = data.get("municipio") or client.city
        client.state = data.get("uf") or client.state
        client.zip_code = data.get("cep") or client.zip_code
        client.updated_at = datetime.utcnow()

    def _serialize_company(self, company: Any) -> Dict[str, Any]:
        """Exporta somente dados necessários para rota e UI."""
        company_get = self._getter(company)

        raw_qsa = company_get("QSA") or company_get("qsa") or []
        qsa = [self._serialize_partner(partner) for partner in raw_qsa]

        return {
            "cnpj": company_get("cnpj"),
            "razao_social": company_get("razao_social"),
            "nome_fantasia": company_get("nome_fantasia"),
            "situacao_cadastral": company_get("situacao_cadastral"),
            "data_inicio_atividade": company_get("data_inicio_atividade"),
            "porte_empresa": company_get("porte_empresa"),
            "natureza_juridica": company_get("natureza_juridica"),
            "logradouro": company_get("logradouro"),
            "numero": company_get("numero"),
            "complemento": company_get("complemento"),
            "bairro": company_get("bairro"),
            "municipio": company_get("municipio"),
            "uf": company_get("uf"),
            "cep": company_get("cep"),
            "email": company_get("email"),
            "qsa": qsa,
        }

    def _serialize_partner(self, partner: Any) -> Dict[str, Any]:
        partner_get = self._getter(partner)
        return {
            "nome_socio": partner_get("nome_socio"),
            "cnpj_cpf_socio": partner_get("cnpj_cpf_socio"),
            "qualificacao_socio": partner_get("qualificacao_socio"),
            "identificador_socio": partner_get("identificador_socio"),
        }

    @staticmethod
    def _getter(value: Any):
        if isinstance(value, dict):
            return lambda key: value.get(key)
        return lambda key: getattr(value, key, None)
