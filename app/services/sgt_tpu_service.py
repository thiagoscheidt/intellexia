import os
import time
from typing import List, Dict, Any

import requests
from zeep import Client, Settings
from zeep.transports import Transport

SGT_WSDL_URL = os.getenv("SGT_WSDL_URL", "https://www.cnj.jus.br/sgt/sgt_ws.php?wsdl")
TPU_API_URL = os.getenv("TPU_API_URL", "https://gateway.cloud.pje.jus.br/tpu")
CACHE_TTL_SECONDS = int(os.getenv("SGT_TPU_CACHE_TTL", "86400"))


class SgtTpuService:
    _cache: Dict[str, Any] = {
        "assuntos": None,
        "assuntos_ts": 0,
        "classes": None,
        "classes_ts": 0,
    }

    def __init__(self, wsdl_url: str = SGT_WSDL_URL, cache_ttl: int = CACHE_TTL_SECONDS):
        self.wsdl_url = wsdl_url
        self.cache_ttl = cache_ttl

    def _get_client(self) -> Client:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/xml,application/xml;q=0.9,*/*;q=0.8",
        })
        settings = Settings(strict=False, xml_huge_tree=True)
        transport = Transport(session=session, timeout=30)
        return Client(self.wsdl_url, settings=settings, transport=transport)

    @staticmethod
    def _get_field(item: Any, field: str) -> Any:
        if item is None:
            return None
        if isinstance(item, dict):
            return item.get(field)
        return getattr(item, field, None)

    @classmethod
    def _normalize_items(cls, items: Any) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        for item in items or []:
            codigo = cls._get_field(item, "codigo") or cls._get_field(item, "seqItem")
            nome = cls._get_field(item, "nome") or cls._get_field(item, "descricao")
            if codigo is None or nome is None:
                continue
            normalized.append({
                "codigo": str(codigo),
                "nome": str(nome)
            })
        normalized.sort(key=lambda x: (x["codigo"].zfill(10), x["nome"]))
        return normalized

    def obter_assuntos_tpu(self) -> List[Dict[str, str]]:
        now = time.time()
        if self._cache["assuntos"] and (now - self._cache["assuntos_ts"]) < self.cache_ttl:
            return self._cache["assuntos"]

        assuntos_rest = self._obter_assuntos_rest()
        if assuntos_rest:
            self._cache["assuntos"] = assuntos_rest
            self._cache["assuntos_ts"] = now
            return assuntos_rest

        try:
            client = self._get_client()
        except Exception as e:
            print(e)
            return []

        items = None
        try:
            items = client.service.pesquisarItemPublicoWS("A", "N", "")
        except Exception as e:
            print(e)
            items = None

        if not items:
            try:
                items = client.service.pesquisarItemPublicoWS("A", "G", "")
            except Exception as e:
                print(e)
                items = None

        if not items:
            try:
                items = client.service.getArrayFilhosItemPublicoWS(0, "A")
            except Exception as e:
                print(e)
                items = None

        if not items:
            print("Nenhum assunto retornado pelo SGT/TPU")
            return []

        assuntos = self._normalize_items(items)
        self._cache["assuntos"] = assuntos
        self._cache["assuntos_ts"] = now
        return assuntos

    def obter_classes_tpu(self) -> List[Dict[str, str]]:
        now = time.time()
        if self._cache["classes"] and (now - self._cache["classes_ts"]) < self.cache_ttl:
            return self._cache["classes"]

        classes_rest = self._obter_classes_rest()
        if classes_rest:
            self._cache["classes"] = classes_rest
            self._cache["classes_ts"] = now
            return classes_rest

        return []

    def _obter_assuntos_rest(self) -> List[Dict[str, str]]:
        url = f"{TPU_API_URL}/api/v1/publico/download/assuntos"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json() if response.content else []
            return self._normalize_rest_items(data)
        except Exception as e:
            print(e)
            return []

    def _obter_classes_rest(self) -> List[Dict[str, str]]:
        url = f"{TPU_API_URL}/api/v1/publico/download/classes"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json() if response.content else []
            return self._normalize_rest_items(data)
        except Exception as e:
            print(e)
            return []

    @classmethod
    def _normalize_rest_items(cls, items: Any) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        for item in items or []:
            codigo = cls._get_field(item, "codigo") or cls._get_field(item, "cod_item") or cls._get_field(item, "codItem")
            nome = cls._get_field(item, "nome") or cls._get_field(item, "descricao")
            if codigo is None or nome is None:
                continue
            normalized.append({
                "codigo": str(codigo),
                "nome": str(nome)
            })
        normalized.sort(key=lambda x: (x["codigo"].zfill(10), x["nome"]))
        return normalized


def obter_assuntos_tpu() -> List[Dict[str, str]]:
    return SgtTpuService().obter_assuntos_tpu()
