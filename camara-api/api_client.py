"""
Cliente para a API de Dados Abertos da Câmara dos Deputados
https://dadosabertos.camara.leg.br/api/v2/
"""

import requests
from typing import Dict, List, Optional
from datetime import datetime


class CamaraAPIClient:
    """Cliente para consumir a API RESTful da Câmara dos Deputados"""
    
    BASE_URL = "https://dadosabertos.camara.leg.br/api/v2"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'Python-Streamlit-App'
        })
    
    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Método auxiliar para fazer requisições GET"""
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e), "dados": []}
    
    # DEPUTADOS
    def listar_deputados(self, nome: Optional[str] = None, 
                        sigla_uf: Optional[str] = None,
                        sigla_partido: Optional[str] = None,
                        pagina: int = 1,
                        itens: int = 15) -> Dict:
        """Lista os deputados com filtros opcionais"""
        params = {
            'pagina': pagina,
            'itens': itens
        }
        if nome:
            params['nome'] = nome
        if sigla_uf:
            params['siglaUf'] = sigla_uf
        if sigla_partido:
            params['siglaPartido'] = sigla_partido
            
        return self._get("deputados", params)
    
    def detalhes_deputado(self, id_deputado: int) -> Dict:
        """Obtém detalhes de um deputado específico"""
        return self._get(f"deputados/{id_deputado}")
    
    def despesas_deputado(self, id_deputado: int, ano: Optional[int] = None,
                         mes: Optional[int] = None, pagina: int = 1, 
                         itens: int = 100) -> Dict:
        """Obtém as despesas de um deputado"""
        params = {'pagina': pagina, 'itens': itens}
        if ano:
            params['ano'] = ano
        if mes:
            params['mes'] = mes
        return self._get(f"deputados/{id_deputado}/despesas", params)
    
    def discursos_deputado(self, id_deputado: int, data_inicio: Optional[str] = None,
                          data_fim: Optional[str] = None, pagina: int = 1,
                          itens: int = 15) -> Dict:
        """Obtém os discursos de um deputado"""
        params = {'pagina': pagina, 'itens': itens, 'ordenarPor': 'dataHoraInicio', 'ordem': 'DESC'}
        if data_inicio:
            params['dataInicio'] = data_inicio
        if data_fim:
            params['dataFim'] = data_fim
        return self._get(f"deputados/{id_deputado}/discursos", params)
    
    def proposicoes_deputado(self, id_deputado: int, pagina: int = 1, 
                            itens: int = 100) -> Dict:
        """Obtém as proposições de autoria de um deputado"""
        params = {
            'idDeputadoAutor': id_deputado,
            'pagina': pagina, 
            'itens': itens, 
            'ordenarPor': 'id', 
            'ordem': 'DESC'
        }
        return self._get("proposicoes", params)
    
    # PROPOSIÇÕES
    def listar_proposicoes(self, sigla_tipo: Optional[str] = None,
                          numero: Optional[int] = None,
                          ano: Optional[int] = None,
                          data_inicio: Optional[str] = None,
                          data_fim: Optional[str] = None,
                          pagina: int = 1,
                          itens: int = 15) -> Dict:
        """Lista proposições com filtros"""
        params = {'pagina': pagina, 'itens': itens}
        if sigla_tipo:
            params['siglaTipo'] = sigla_tipo
        if numero:
            params['numero'] = numero
        # Não usar 'ano' se dataInicio/dataFim estão definidos (conflito na API)
        if data_inicio or data_fim:
            if data_inicio:
                params['dataInicio'] = data_inicio
            if data_fim:
                params['dataFim'] = data_fim
        elif ano:
            params['ano'] = ano
            
        return self._get("proposicoes", params)
    
    def detalhes_proposicao(self, id_proposicao: int) -> Dict:
        """Obtém detalhes de uma proposição"""
        return self._get(f"proposicoes/{id_proposicao}")
    
    def autores_proposicao(self, id_proposicao: int) -> Dict:
        """Obtém os autores de uma proposição"""
        return self._get(f"proposicoes/{id_proposicao}/autores")
    
    def tramitacoes_proposicao(self, id_proposicao: int) -> Dict:
        """Obtém a tramitação de uma proposição"""
        return self._get(f"proposicoes/{id_proposicao}/tramitacoes")
    
    def temas_proposicao(self, id_proposicao: int) -> Dict:
        """Obtém os temas de uma proposição"""
        return self._get(f"proposicoes/{id_proposicao}/temas")
    
    def votacoes_proposicao(self, id_proposicao: int) -> Dict:
        """Obtém as votações de uma proposição"""
        return self._get(f"proposicoes/{id_proposicao}/votacoes")
    
    # PARTIDOS
    def listar_partidos(self, sigla: Optional[str] = None,
                       data_inicio: Optional[str] = None,
                       data_fim: Optional[str] = None,
                       pagina: int = 1,
                       itens: int = 15) -> Dict:
        """Lista os partidos políticos"""
        params = {'pagina': pagina, 'itens': itens}
        if sigla:
            params['sigla'] = sigla
        if data_inicio:
            params['dataInicio'] = data_inicio
        if data_fim:
            params['dataFim'] = data_fim
            
        return self._get("partidos", params)
    
    def detalhes_partido(self, id_partido: int) -> Dict:
        """Obtém detalhes de um partido"""
        return self._get(f"partidos/{id_partido}")
    
    def membros_partido(self, id_partido: int, pagina: int = 1, 
                       itens: int = 15) -> Dict:
        """Lista os membros de um partido"""
        params = {'pagina': pagina, 'itens': itens}
        return self._get(f"partidos/{id_partido}/membros", params)
    
    # BLOCOS
    def listar_blocos(self, pagina: int = 1, itens: int = 15) -> Dict:
        """Lista os blocos parlamentares"""
        params = {'pagina': pagina, 'itens': itens}
        return self._get("blocos", params)
    
    # EVENTOS
    def listar_eventos(self, data_inicio: Optional[str] = None,
                      data_fim: Optional[str] = None,
                      pagina: int = 1,
                      itens: int = 15) -> Dict:
        """Lista eventos da Câmara"""
        params = {'pagina': pagina, 'itens': itens}
        if data_inicio:
            params['dataInicio'] = data_inicio
        if data_fim:
            params['dataFim'] = data_fim
            
        return self._get("eventos", params)
    
    def detalhes_evento(self, id_evento: int) -> Dict:
        """Obtém detalhes de um evento"""
        return self._get(f"eventos/{id_evento}")
    
    # VOTAÇÕES
    def listar_votacoes(self, id_proposicao: Optional[int] = None,
                       pagina: int = 1,
                       itens: int = 15) -> Dict:
        """Lista votações - usa ID da proposição como filtro"""
        params = {'pagina': pagina, 'itens': itens, 'ordem': 'DESC', 'ordenarPor': 'dataHoraRegistro'}
        if id_proposicao:
            params['idProposicao'] = id_proposicao
            
        return self._get("votacoes", params)
    
    def detalhes_votacao(self, id_votacao: str) -> Dict:
        """Obtém detalhes de uma votação"""
        return self._get(f"votacoes/{id_votacao}")
    
    def votos_votacao(self, id_votacao: str) -> Dict:
        """Obtém os votos de uma votação"""
        return self._get(f"votacoes/{id_votacao}/votos")
    
    # ORGÃOS
    def listar_orgaos(self, sigla: Optional[str] = None,
                     pagina: int = 1,
                     itens: int = 15) -> Dict:
        """Lista os órgãos da Câmara"""
        params = {'pagina': pagina, 'itens': itens}
        if sigla:
            params['sigla'] = sigla
            
        return self._get("orgaos", params)
    
    def detalhes_orgao(self, id_orgao: int) -> Dict:
        """Obtém detalhes de um órgão"""
        return self._get(f"orgaos/{id_orgao}")
    
    def membros_orgao(self, id_orgao: int, pagina: int = 1, 
                     itens: int = 15) -> Dict:
        """Lista os membros de um órgão"""
        params = {'pagina': pagina, 'itens': itens}
        return self._get(f"orgaos/{id_orgao}/membros", params)
    
    # REFERÊNCIAS
    def tipos_proposicao(self) -> Dict:
        """Obtém a lista de tipos de proposição"""
        return self._get("referencias/tiposProposicao")
