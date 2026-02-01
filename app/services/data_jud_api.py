import os
from dotenv import load_dotenv
import requests
from typing import Dict, List, Optional, Any

load_dotenv()

DATA_JUD_API_URL = os.getenv('DATA_JUD_API_URL', 'https://api-publica.datajud.cnj.jus.br')
DATA_JUD_API_KEY = os.getenv('DATA_JUD_API_KEY', 'cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw==')

class DataJudAPI:
    """
    Cliente para API Pública do DataJud - CNJ
    Documentação: https://datajud-wiki.cnj.jus.br/api-publica/
    """
    
    # Tribunais disponíveis
    TRIBUNAIS = {
        'STF': 'api_publica_stf',
        'STJ': 'api_publica_stj',
        'TST': 'api_publica_tst',
        'TSE': 'api_publica_tse',
        'STM': 'api_publica_stm',
        'TRF1': 'api_publica_trf1',
        'TRF2': 'api_publica_trf2',
        'TRF3': 'api_publica_trf3',
        'TRF4': 'api_publica_trf4',
        'TRF5': 'api_publica_trf5',
        'TRF6': 'api_publica_trf6',
        'TJAC': 'api_publica_tjac',
        'TJAL': 'api_publica_tjal',
        'TJAM': 'api_publica_tjam',
        'TJAP': 'api_publica_tjap',
        'TJBA': 'api_publica_tjba',
        'TJCE': 'api_publica_tjce',
        'TJDFT': 'api_publica_tjdft',
        'TJES': 'api_publica_tjes',
        'TJGO': 'api_publica_tjgo',
        'TJMA': 'api_publica_tjma',
        'TJMG': 'api_publica_tjmg',
        'TJMS': 'api_publica_tjms',
        'TJMT': 'api_publica_tjmt',
        'TJPA': 'api_publica_tjpa',
        'TJPB': 'api_publica_tjpb',
        'TJPE': 'api_publica_tjpe',
        'TJPI': 'api_publica_tjpi',
        'TJPR': 'api_publica_tjpr',
        'TJRJ': 'api_publica_tjrj',
        'TJRN': 'api_publica_tjrn',
        'TJRO': 'api_publica_tjro',
        'TJRR': 'api_publica_tjrr',
        'TJRS': 'api_publica_tjrs',
        'TJSC': 'api_publica_tjsc',
        'TJSE': 'api_publica_tjse',
        'TJSP': 'api_publica_tjsp',
        'TJTO': 'api_publica_tjto',
    }
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Inicializa o cliente da API DataJud
        
        Args:
            api_key: Chave de API. Se não fornecida, usa a variável de ambiente.
        """
        self.api_url = DATA_JUD_API_URL
        self.api_key = api_key or DATA_JUD_API_KEY
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'APIKey {self.api_key}',
            'Content-Type': 'application/json'
        })
    
    def _get_endpoint(self, tribunal: str) -> str:
        """
        Obtém o endpoint correto para o tribunal
        
        Args:
            tribunal: Sigla do tribunal (ex: TRF1, TJSP, STF)
            
        Returns:
            Nome do índice/endpoint da API
        """
        tribunal_upper = tribunal.upper()
        if tribunal_upper not in self.TRIBUNAIS:
            raise ValueError(f"Tribunal '{tribunal}' não é válido. Tribunais disponíveis: {', '.join(self.TRIBUNAIS.keys())}")
        return self.TRIBUNAIS[tribunal_upper]
    
    def buscar_por_numero_processo(
        self,
        numero_processo: str,
        tribunal: str,
        size: int = 10
    ) -> Dict[str, Any]:
        """
        Busca processos pelo número único (CNJ)
        
        Args:
            numero_processo: Número do processo (apenas dígitos, sem formatação)
            tribunal: Sigla do tribunal (ex: TRF1, TJSP)
            size: Quantidade de resultados (padrão: 10)
            
        Returns:
            Dicionário com os resultados da busca
            
        Example:
            >>> api = DataJudAPI()
            >>> resultado = api.buscar_por_numero_processo('00008323520184013202', 'TRF1')
        """
        endpoint = self._get_endpoint(tribunal)
        url = f"{self.api_url}/{endpoint}/_search"
        
        # Remove formatação do número do processo
        numero_limpo = ''.join(filter(str.isdigit, numero_processo))
        
        query = {
            "query": {
                "match": {
                    "numeroProcesso": numero_limpo
                }
            },
            "size": size
        }
        
        try:
            response = self.session.post(url, json=query, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            status_code = getattr(e.response, 'status_code', None)
            message = str(e)
            if status_code == 404:
                message = f"Tribunal '{tribunal}' não disponível na API pública do DataJud."
            details = None
            if getattr(e, 'response', None) is not None:
                try:
                    details = e.response.text
                except Exception:
                    details = None
            if details:
                message = f"{message} | {details}"
            return {
                'error': True,
                'message': message,
                'status_code': status_code
            }
    
    def buscar_por_classe_e_orgao(
        self,
        codigo_classe: int,
        codigo_orgao: int,
        tribunal: str,
        size: int = 10
    ) -> Dict[str, Any]:
        """
        Busca processos por classe processual e órgão julgador
        
        Args:
            codigo_classe: Código da classe processual (TPU)
            codigo_orgao: Código do órgão julgador
            tribunal: Sigla do tribunal
            size: Quantidade de resultados
            
        Returns:
            Dicionário com os resultados da busca
        """
        endpoint = self._get_endpoint(tribunal)
        url = f"{self.api_url}/{endpoint}/_search"
        
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"match": {"classe.codigo": codigo_classe}},
                        {"match": {"orgaoJulgador.codigo": codigo_orgao}}
                    ]
                }
            },
            "size": size
        }
        
        try:
            response = self.session.post(url, json=query, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            status_code = getattr(e.response, 'status_code', None)
            message = str(e)
            if status_code == 404:
                message = f"Tribunal '{tribunal}' não disponível na API pública do DataJud."
            return {
                'error': True,
                'message': message,
                'status_code': status_code
            }
    
    def buscar_com_paginacao(
        self,
        query: Dict[str, Any],
        tribunal: str,
        size: int = 100,
        search_after: Optional[List] = None
    ) -> Dict[str, Any]:
        """
        Busca com paginação usando search_after
        
        Args:
            query: Query DSL do Elasticsearch
            tribunal: Sigla do tribunal
            size: Tamanho da página (máximo recomendado: 100)
            search_after: Array com valores de ordenação do último resultado
            
        Returns:
            Dicionário com os resultados da busca
            
        Example:
            >>> query = {"query": {"match_all": {}}}
            >>> resultado = api.buscar_com_paginacao(query, 'TRF1', size=100)
            >>> # Próxima página
            >>> sort_values = resultado['hits']['hits'][-1]['sort']
            >>> prox_pag = api.buscar_com_paginacao(query, 'TRF1', size=100, search_after=sort_values)
        """
        endpoint = self._get_endpoint(tribunal)
        url = f"{self.api_url}/{endpoint}/_search"
        
        # Garante que há ordenação para usar search_after
        if 'sort' not in query:
            query['sort'] = [{"_id": "asc"}]
        
        query['size'] = size
        
        if search_after:
            query['search_after'] = search_after
        
        try:
            response = self.session.post(url, json=query, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            status_code = getattr(e.response, 'status_code', None)
            message = str(e)
            if status_code == 404:
                message = f"Tribunal '{tribunal}' não disponível na API pública do DataJud."
            return {
                'error': True,
                'message': message,
                'status_code': status_code
            }
    
    def buscar_por_assunto(
        self,
        codigo_assunto: int,
        tribunal: str,
        size: int = 10
    ) -> Dict[str, Any]:
        """
        Busca processos por código de assunto (TPU)
        
        Args:
            codigo_assunto: Código do assunto processual
            tribunal: Sigla do tribunal
            size: Quantidade de resultados
            
        Returns:
            Dicionário com os resultados
        """
        endpoint = self._get_endpoint(tribunal)
        url = f"{self.api_url}/{endpoint}/_search"
        
        query = {
            "query": {
                "nested": {
                    "path": "assuntos",
                    "query": {
                        "match": {
                            "assuntos.codigo": codigo_assunto
                        }
                    }
                }
            },
            "size": size
        }
        
        try:
            response = self.session.post(url, json=query, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            status_code = getattr(e.response, 'status_code', None)
            message = str(e)
            if status_code == 404:
                message = f"Tribunal '{tribunal}' não disponível na API pública do DataJud."
            return {
                'error': True,
                'message': message,
                'status_code': status_code
            }
    
    def buscar_movimentos_por_codigo(
        self,
        codigo_movimento: int,
        tribunal: str,
        data_inicio: Optional[str] = None,
        data_fim: Optional[str] = None,
        size: int = 10
    ) -> Dict[str, Any]:
        """
        Busca processos que possuem determinado movimento processual
        
        Args:
            codigo_movimento: Código do movimento (TPU)
            tribunal: Sigla do tribunal
            data_inicio: Data inicial (formato: YYYY-MM-DD)
            data_fim: Data final (formato: YYYY-MM-DD)
            size: Quantidade de resultados
            
        Returns:
            Dicionário com os resultados
        """
        endpoint = self._get_endpoint(tribunal)
        url = f"{self.api_url}/{endpoint}/_search"
        
        must_conditions = [
            {
                "nested": {
                    "path": "movimentos",
                    "query": {
                        "match": {
                            "movimentos.codigo": codigo_movimento
                        }
                    }
                }
            }
        ]
        
        # Adiciona filtro de data se fornecido
        if data_inicio or data_fim:
            date_filter = {}
            if data_inicio:
                date_filter["gte"] = data_inicio
            if data_fim:
                date_filter["lte"] = data_fim
            
            must_conditions.append({
                "nested": {
                    "path": "movimentos",
                    "query": {
                        "range": {
                            "movimentos.dataHora": date_filter
                        }
                    }
                }
            })
        
        query = {
            "query": {
                "bool": {
                    "must": must_conditions
                }
            },
            "size": size
        }
        
        try:
            response = self.session.post(url, json=query, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {
                'error': True,
                'message': str(e),
                'status_code': getattr(e.response, 'status_code', None)
            }
    
    def extrair_processos(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extrai a lista de processos da resposta da API
        
        Args:
            response: Resposta da API
            
        Returns:
            Lista de processos encontrados
        """
        if response.get('error'):
            return []
        
        hits = response.get('hits', {}).get('hits', [])
        return [hit['_source'] for hit in hits]
    
    def obter_total_resultados(self, response: Dict[str, Any]) -> int:
        """
        Obtém o total de resultados da busca
        
        Args:
            response: Resposta da API
            
        Returns:
            Total de resultados
        """
        if response.get('error'):
            return 0
        
        return response.get('hits', {}).get('total', {}).get('value', 0)


def main():
    """
    Função de teste para buscar processo pelo número
    """
    print("=" * 80)
    print("TESTE DA API DATAJUD - BUSCA POR NÚMERO DE PROCESSO")
    print("=" * 80)
    
    # Inicializar API
    api = DataJudAPI()
    
    # Exemplo: Processo do TRF1
    numero_processo = "5004423-11.2025.4.04.7107"
    tribunal = "TRF4"
    
    print(f"\n🔍 Buscando processo: {numero_processo}")
    print(f"📍 Tribunal: {tribunal}")
    print("\nAguarde...\n")
    
    # Realizar busca
    resultado = api.buscar_por_numero_processo(
        numero_processo=numero_processo,
        tribunal=tribunal,
        size=10
    )

    print(resultado)
    exit()
    
    # Verificar se houve erro
    if resultado.get('error'):
        print(f"❌ ERRO na busca:")
        print(f"   Mensagem: {resultado.get('message')}")
        print(f"   Status Code: {resultado.get('status_code')}")
        return
    
    # Exibir informações da busca
    total = api.obter_total_resultados(resultado)
    print(f"✅ Busca concluída!")
    print(f"📊 Total de resultados encontrados: {total}")
    print(f"⏱️  Tempo de processamento: {resultado.get('took', 0)}ms")
    
    # Extrair e exibir processos
    processos = api.extrair_processos(resultado)
    
    if processos:
        print(f"\n{'=' * 80}")
        print("DETALHES DO PROCESSO")
        print('=' * 80)
        
        for i, processo in enumerate(processos, 1):
            print(f"\n📋 Processo {i}:")
            print(f"   ID: {processo.get('id')}")
            print(f"   Número: {processo.get('numeroProcesso')}")
            print(f"   Tribunal: {processo.get('tribunal')}")
            print(f"   Grau: {processo.get('grau')}")
            
            # Classe processual
            classe = processo.get('classe', {})
            if classe:
                print(f"   Classe: [{classe.get('codigo')}] {classe.get('nome')}")
            
            # Órgão julgador
            orgao = processo.get('orgaoJulgador', {})
            if orgao:
                print(f"   Órgão Julgador: [{orgao.get('codigo')}] {orgao.get('nome')}")
                print(f"   Município IBGE: {orgao.get('codigoMunicipioIBGE')}")
            
            # Data de ajuizamento
            data_ajuizamento = processo.get('dataAjuizamento')
            if data_ajuizamento:
                print(f"   Data Ajuizamento: {data_ajuizamento}")
            
            # Sistema
            sistema = processo.get('sistema', {})
            if sistema:
                print(f"   Sistema: {sistema.get('nome')}")
            
            # Formato
            formato = processo.get('formato', {})
            if formato:
                print(f"   Formato: {formato.get('nome')}")
            
            # Nível de sigilo
            print(f"   Nível Sigilo: {processo.get('nivelSigilo', 0)}")
            
            # Assuntos
            assuntos = processo.get('assuntos', [])
            if assuntos:
                print(f"\n   📑 Assuntos ({len(assuntos)}):")
                for assunto in assuntos[:5]:  # Mostra até 5 assuntos
                    print(f"      • [{assunto.get('codigo')}] {assunto.get('nome')}")
                if len(assuntos) > 5:
                    print(f"      ... e mais {len(assuntos) - 5} assuntos")
            
            # Movimentos
            movimentos = processo.get('movimentos', [])
            if movimentos:
                print(f"\n   📅 Movimentos ({len(movimentos)}):")
                for movimento in movimentos[:5]:  # Mostra últimos 5 movimentos
                    print(f"      • [{movimento.get('codigo')}] {movimento.get('nome')}")
                    print(f"        Data: {movimento.get('dataHora')}")
                if len(movimentos) > 5:
                    print(f"      ... e mais {len(movimentos) - 5} movimentos")
            
            print(f"\n   🕐 Última atualização: {processo.get('dataHoraUltimaAtualizacao')}")
    else:
        print("\n⚠️  Nenhum processo encontrado com esse número.")
    
    print(f"\n{'=' * 80}")
    print("FIM DO TESTE")
    print('=' * 80)


if __name__ == "__main__":
    main()

