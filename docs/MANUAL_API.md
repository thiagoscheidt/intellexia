# Manual do Usuário — API do IntellexIA

> A API entrega os dados do escritório (benefícios, contestações, segurados, base de conhecimento, jurisprudência e processos) para quem quer montar as próprias telas, planilhas e automações, com o Claude Code ou qualquer outra ferramenta.

---

## O que é

A API é a mesma base que você vê nas telas e no conector do Claude, entregue em formato de dados (JSON). Com ela, em vez de esperar uma tela nova, você pede ao Claude Code algo como "monta uma tela que filtra os B91 indeferidos da Vale" e ele busca os dados direto do IntellexIA.

- **Mesmos números das telas e do Claude.** A API usa as mesmas consultas do conector do Claude.
- **Só leitura.** Nada é alterado pela API. A única exceção é revelar o nome de um segurado, que grava o nome como o botão da tela faz. A consulta completa de CPF (`POST /segurados/consultar-cpf`) devolve tudo o que o serviço de consulta traz (nome, nascimento, sexo, nome da mãe) e não grava nada.
- **Só o seu escritório e só o que você pode ver.** Se você não tem acesso ao Painel de Processos na tela, também não tem pela API.

---

## Quem tem acesso

A API faz parte do módulo **API e integrações**, liberado para todos por padrão. O administrador pode retirá-lo de um usuário na **Administração de Usuários**.

---

## Criar o seu token

O token é a sua chave pessoal para a API: quem tem o token age em seu nome.

1. Clique no botão **{ }** do cabeçalho, ao lado do ícone do Claude (ou abra **Minha API** no menu do usuário).
2. Dê um nome ao token (ex.: "Claude Code do notebook"), escolha a validade (30, 90 ou 180 dias, ou sem validade) e clique em :btn-primary[Criar token].
3. Copie o token na hora. **Ele aparece uma vez só**; depois a tela mostra apenas o final (ex.: `…a3f9`).

Também dá para pedir ao Claude, pelo conector: "crie um token de API para mim".

> [!ALERTA] Trate o token como uma senha. Guarde numa variável de ambiente (`INTELLEXIA_TOKEN`) ou num `.env` que não vai para o git, e não publique fora do escritório uma página que contenha o token. Perdeu ou desconfia que vazou? Revogue em **Minha API** e crie outro: o antigo para de funcionar na hora.

O token deixa de funcionar sozinho quando vence, quando é revogado ou quando o usuário é desativado.

---

## Usar no Claude Code

1. Guarde o token: `export INTELLEXIA_TOKEN=itx_...` (ou no `.env` do projeto, fora do git).
2. Peça ao Claude Code, citando a documentação:

> Use a API do IntellexIA (documentação em :url_app:/api/v1/openapi.json, token na variável INTELLEXIA_TOKEN) para montar uma tela que lista os benefícios B91 indeferidos na 1ª instância de uma empresa, com filtro por vigência.

O botão **{ }** do cabeçalho traz uma mini documentação (endereço, exemplo e a lista de rotas), seus tokens e a criação de token. A documentação completa fica em **Minha API → Documentação**: para cada rota, os parâmetros, um exemplo de chamada, **os campos que ela devolve** (nome, tipo e o que significa) e um exemplo da resposta em JSON. É o que o Claude Code precisa para montar a tela sem adivinhar.

---

## Como a API responde

| Situação | O que volta |
|---|---|
| Deu certo | Os dados em JSON, com os campos descritos na documentação de cada rota. Campo sem valor vem `null` |
| Lista grande | `limite` (até 1.000 por página) e `deslocamento` para paginar; a resposta traz `tem_mais` e `proximo_deslocamento` |
| `limite` acima do máximo da rota | Erro 400 dizendo o máximo — a API nunca corta a página sem avisar |
| Filtro com nome errado ou valor inválido | Erro 400 dizendo qual parâmetro e quais são aceitos |
| Token ausente, vencido ou revogado | Erro 401 |
| Sem acesso ao módulo | Erro 403 |
| Registro que não existe no escritório | Erro 404 |
| Limite atingido | Erro 429 |

Todo erro vem no formato `{"erro": "mensagem"}`.

---

## Limites

| O quê | Limite |
|---|---|
| Chamadas por token | 120 por minuto |
| Registros por página | 1.000 (a pesquisa na Base de Conhecimento vai até 50 trechos e as decisões parecidas até 20) |
| Revelar nome e consulta completa de CPF (consultas pagas) | A mesma cota diária do Claude, somada: o que você consultar pelo Claude e pela API, nas duas, conta junto |

O uso da API aparece para o administrador em **Atividade de Usuários**, ao lado do uso do conector do Claude (só o nome da rota e a quantidade, nunca o que foi pesquisado).
