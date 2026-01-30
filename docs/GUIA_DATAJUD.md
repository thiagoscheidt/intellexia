# Ferramenta DataJud - Guia de Uso

## 📋 Visão Geral

A ferramenta DataJud permite **consultar processos judiciais em tempo real** diretamente dos tribunais brasileiros através da API Pública do CNJ (Conselho Nacional de Justiça). É uma ferramenta **apenas de consulta** (read-only) que não permite modificações nos dados.

## 🚀 Como Acessar

1. No menu lateral esquerdo, clique em **Ferramentas** → **Pesquisa DataJud**
2. Ou acesse diretamente: `seu-dominio.com/tools/datajud`

## 🔍 Tipos de Busca

A ferramenta oferece 3 tipos de busca diferentes:

### 1️⃣ Busca por Número (Por Número)

**Quando usar:** Quando você conhece o número CNJ exato do processo

- **Campo:** Número do Processo
- **Formato aceito:** Ambos os formatos
  - Formatado: `0000832-35.2018.4.01.3202`
  - Não formatado: `00008323520184013202`
- **Campo:** Tribunal (obrigatório)
  - Selecione o tribunal onde o processo está registrado

**Exemplo:**
```
Número: 0000832-35.2018.4.01.3202
Tribunal: TRF 1ª Região (TRF1)
```

---

### 2️⃣ Busca por Classe (Por Classe)

**Quando usar:** Quando você quer buscar todos os processos de um tipo específico em um tribunal

- **Código da Classe:** Código TPU da classe processual
- **Código do Órgão:** (Opcional) Deixe vazio para buscar em todo o tribunal
- **Tribunal:** (Obrigatório) Tribunal onde buscar

**Códigos de Classe Comuns (TPU):**
- `436` - Juizado Especial Cível
- `1101` - Ação Cível Originária
- `2167` - Embargos à Execução
- `7000` - Mandado de Segurança

**Exemplo:**
```
Código da Classe: 436
Tribunal: TJSP - São Paulo
Resultado: Todos os processos de Juizado Especial Cível em São Paulo
```

---

### 3️⃣ Busca por Assunto (Por Assunto)

**Quando usar:** Quando você quer buscar processos por matéria/assunto

- **Código do Assunto:** Código TPU do assunto processual
- **Tribunal:** (Obrigatório) Tribunal onde buscar

**Códigos de Assunto Comuns (TPU):**
- `6177` - Concessão de Benefício Previdenciário
- `7716` - Auxílio-Doença
- `7714` - Pensão por Morte
- `7713` - Aposentadoria por Invalidez

**Exemplo:**
```
Código do Assunto: 6177
Tribunal: TRF 1ª Região
Resultado: Todos os processos de concessão de benefício na TRF1
```

---

## 📊 Resultados

Quando uma busca retorna resultados, você verá:

| Campo | Descrição |
|-------|-----------|
| **Número** | Número CNJ formatado do processo |
| **Classe** | Tipo de ação (código e nome) |
| **Tribunal** | Tribunal competente |
| **Órgão Julgador** | Vara ou Seção responsável |
| **Data Ajuizamento** | Data em que o processo foi registrado |
| **Status** | Público ou Sigiloso |

### Seção "Movimentos Recentes"

Cada processo mostra seus últimos 3 movimentos com:
- **Data** do movimento
- **Nome** do movimento (decisão, intimação, etc)

### Seção "Assuntos"

Lista todos os assuntos relacionados ao processo (máximo 3 mostrados)

---

## 🎯 Tribunais Disponíveis

A ferramenta suporta os seguintes tribunais:

### Superiores
- **STF** - Supremo Tribunal Federal
- **STJ** - Superior Tribunal de Justiça
- **TST** - Tribunal Superior do Trabalho

### Federais
- **TRF1** - TRF 1ª Região (Brasília)
- **TRF2** - TRF 2ª Região (Rio de Janeiro)
- **TRF3** - TRF 3ª Região (São Paulo)
- **TRF4** - TRF 4ª Região (Rio Grande do Sul)
- **TRF5** - TRF 5ª Região (Bahia/Pernambuco)
- **TRF6** - TRF 6ª Região (Minas Gerais)

### Estaduais (Principais)
- **TJSP** - TJSP - São Paulo
- **TJRJ** - TJRJ - Rio de Janeiro
- **TJMG** - TJMG - Minas Gerais
- **TJBA** - TJBA - Bahia
- **TJRS** - TJRS - Rio Grande do Sul
- **TJSC** - TJSC - Santa Catarina
- **TJPB** - TJPB - Paraíba
- **TJPE** - TJPE - Pernambuco
- **TJCE** - TJCE - Ceará
- **TJPA** - TJPA - Pará
- **TJPR** - TJPR - Paraná

---

## ⚠️ Limitações e Dicas

### Limitações
1. **Consulta apenas** - A ferramenta não permite criar, editar ou deletar dados
2. **Limite de resultados** - Máximo ~100 processos por busca para otimizar performance
3. **Disponibilidade** - Depende da disponibilidade da API do CNJ (normalmente 24/7)
4. **Tempo de busca** - Pode variar de 100ms a 5000ms conforme o volume de dados

### Dicas
- ✅ Use a busca por **número** se você conhecer o processo exato
- ✅ Use a busca por **classe** para monitorar casos por tipo
- ✅ Use a busca por **assunto** para análises estatísticas
- ⚠️ Os códigos TPU podem variar entre tribunais - consulte a [tabela oficial](https://www.cnj.jus.br/sgt/versoes.php)
- 🔄 Os dados são atualizados em tempo real (latência da API CNJ)

---

## 🔗 Integração com Casos

**Próximo passo:** Os dados obtidos na pesquisa podem ser manualmente copiados para seus casos no Intellexia para:
- ✏️ Atualizar informações processuais
- 📝 Adicionar movimentos importantes
- 🏷️ Organizar por classe/assunto

---

## 📚 Recursos Adicionais

### Links Oficiais
- **Wiki Oficial DataJud:** https://datajud-wiki.cnj.jus.br/api-publica/
- **Tabela de Códigos TPU:** https://www.cnj.jus.br/sgt/versoes.php
- **Glossário de Dados:** https://datajud-wiki.cnj.jus.br/api-publica/glossario

### Suporte
Para dúvidas sobre códigos específicos ou comportamento da API:
- 📧 Email: datajud@cnj.jus.br
- 💬 Central de atendimento CNJ
- 📖 Documentação técnica completa em docs/API_DATAJUD.md

---

## 🛠️ Configurações Técnicas

A ferramenta está configurada com:
- **API:** DataJud Pública (sem autenticação necessária)
- **Timeout:** 30 segundos por busca
- **Formato:** JSON Elasticsearch Query DSL
- **Taxa limite:** Não limitado (verificar com CNJ)

Para alterar configurações, edite `.env`:
```bash
DATA_JUD_API_URL=https://api-publica.datajud.cnj.jus.br
DATA_JUD_API_KEY=sua_chave_aqui  # Opcional, já tem padrão
```

---

## ❓ Perguntas Frequentes

**P: Por que recebo "Nenhum resultado encontrado"?**  
R: Verifique se o tribunal está correto e se o processo existe. Alguns processos podem ser sigilosos.

**P: Qual é o tempo de resposta?**  
R: Varia de 100ms a 5s, conforme o volume de dados no tribunal. Geralmente mais rápido para buscas específicas.

**P: Posso exportar os dados?**  
R: Atualmente não. Você pode copiar manualmente as informações.

**P: A busca é em tempo real?**  
R: Sim! Os dados vêm diretamente dos servidores do CNJ.

---

**Última atualização:** Dezembro 2024
