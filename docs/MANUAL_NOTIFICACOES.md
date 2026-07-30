# Manual do Usuário — Notificações por E-mail

> Documentação funcional das notificações automáticas por e-mail do IntellexIA. Explica **quais resumos existem**, **como configurá-los** e **como ler cada e-mail**, em linguagem de negócio.

---

## O que são as notificações

O IntellexIA envia, por e-mail, **resumos automáticos** do que aconteceu no sistema — sem que ninguém precise abrir os painéis para conferir. Cada escritório configura as suas notificações de forma independente.

Hoje existem três tipos de resumo:

| Notificação | O que traz | De qual painel vem |
|---|---|---|
| **Resumo FAP** | Novidades das contestações FAP sincronizadas do FAP Web (publicações no D.O.U., novas contestações e atualizações). | Painel FAP / widget do Dashboard |
| **Comunicações processuais (DJEN)** | Comunicações novas recebidas do Diário de Justiça Eletrônico Nacional, com destaque para decisões e sentenças. | Monitoramento de Processos |
| **Radar — Monitoramento de Processos** | Pendências abertas da mesa de trabalho: providências sugeridas pela IA, publicações não lidas e movimentações de processos. | Painel de Processos (widget Radar) |

> [!INFO] O conteúdo de cada e-mail é gerado pelas **mesmas regras das telas**. O Resumo FAP, por exemplo, usa exatamente os mesmos dados do painel "Contestações FAP — recentes" do Dashboard: o que você vê no e-mail é o que veria na tela.

---

## Como configurar

A configuração fica em **Configurações → Notificações** e é **exclusiva de administradores**. A tela mostra um cartão por tipo de notificação, cada um com:

- **Chave de ativação** — liga/desliga aquela notificação para o escritório.
- **Frequência** — *Diária* ou *Semanal* (na semanal, escolhe-se também o **dia da semana**).
- **Horário** — hora do envio, em **horário de Brasília**.
- **Destinatários** — lista de e-mails que receberão o resumo (não precisam ser usuários do sistema).

Depois de salvar, use :btn-outline-secondary[Enviar teste para mim] para receber na hora uma amostra do e-mail com os dados reais do escritório — o teste vai **só para o e-mail escolhido** e **não afeta o agendamento** nem os demais destinatários. Também é possível enviar o teste para outro usuário do escritório.

> [!ALERTA] O envio depende do **servidor de e-mail** da instalação estar configurado (feito pela equipe técnica). Se os testes não chegarem, verifique a caixa de spam e, persistindo, acione o suporte.

---

## Quando o e-mail chega

- O sistema verifica os agendamentos **de hora em hora** e envia cada resumo no horário configurado.
- O e-mail **só é enviado quando há novidade** desde o último envio. Sem novidade no período, nada é enviado — você não recebe e-mails vazios.
- Se um envio falhar (ex.: problema momentâneo no servidor de e-mail), o sistema **tenta novamente na próxima hora**, sem perder o período.

---

## Resumo FAP — como ler o e-mail

O assunto do e-mail indica quantas contestações tiveram novidade (ex.: *"Resumo FAP — 22 contestações com novidade"*). O corpo é dividido em **dois blocos**:

1. **"O que mudou no período"** — apresenta apenas as novidades desde o último envio, ou seja, os eventos que motivaram o disparo do e-mail.
2. **"Mais recentes"** — exibe a situação atual do painel, listando as 10 contestações mais recentes de cada tabela, independentemente de quando ocorreram as alterações.

Por esse motivo, alguns registros podem aparecer em ambos os blocos.

Dentro de cada bloco há até **três tabelas**:

### Publicadas no D.O.U.

Reúne as contestações que **receberam data de publicação no Diário Oficial da União**. A data exibida corresponde ao **dia da publicação** e, por isso, pode ser futura (por exemplo, 30/07 indica que a publicação ocorrerá no Diário Oficial dessa data).

> [!DOU] Recomendamos acompanhar essa tabela com atenção, pois a publicação no D.O.U. normalmente marca o **início dos prazos**.

### Cadastradas

Apresenta as contestações **identificadas pela primeira vez** durante a sincronização com o FAP Web. Essa lista pode incluir contestações de vigências anteriores que passaram a ser monitoradas recentemente — "cadastrada agora" significa que **entrou agora no IntellexIA**, não que a contestação seja nova no FAP Web.

### Atualizadas

Mostra as contestações que **já estavam cadastradas** no painel e tiveram alguma alteração no FAP Web desde o último resumo. A coluna **"Alterou"** informa exatamente qual foi a mudança — por exemplo, *"Publicação D.O.U."* indica que a contestação ganhou data de publicação no Diário.

### Colunas comuns

| Coluna | O que é |
|---|---|
| **Empresa** | Nome e CNPJ do estabelecimento da contestação. |
| **Protocolo** | Número do protocolo da contestação no FAP Web. |
| **Situação** | Situação atual (ex.: "Transmitida") e a instância administrativa (1ª ou 2ª). |
| **Vigência** | Ano de vigência FAP que está sendo contestado. |

---

## Comunicações processuais (DJEN) — como ler o e-mail

Lista as **comunicações processuais novas** recebidas no período (intimações, publicações, etc.), as mesmas que aparecem no painel de Monitoramento de Processos. Comunicações que contêm **decisão ou sentença** vêm destacadas, para priorizar a leitura. Cada item traz link direto para abrir a comunicação no sistema.

---

## Radar — como ler o e-mail

Mostra o **estado atual do Radar** da mesa de trabalho: providências sugeridas pela IA, publicações ainda não lidas e movimentações recentes dos processos acompanhados. O e-mail só é disparado quando **entrou item novo** no Radar desde o último envio — mas o corpo sempre reflete a foto atual das pendências abertas, com decisões e sentenças em destaque.
