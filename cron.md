# Configuração de Cron - IntellexIA

Este arquivo contém um modelo de configuração de `cron` para processar filas pendentes dos scripts no servidor.

## 1) Pré-requisitos no servidor

- Projeto publicado em: `/opt/intellexia`
- `uv` instalado e funcional para o usuário que executa o cron
- Arquivo `.env` configurado em `/opt/intellexia/.env`
- Permissões de escrita em `/var/log/intellexia`

Crie diretório de logs:

```bash
sudo mkdir -p /var/log/intellexia
sudo chown -R $USER:$USER /var/log/intellexia
```

## 2) Entradas recomendadas no crontab

Abra o crontab do usuário da aplicação:

```bash
crontab -e
```

Cole o bloco abaixo (ajuste caminhos/usuário se necessário):

```cron
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin

# Processa base de conhecimento pendente (a cada 5 minutos)
*/5 * * * * cd /opt/intellexia && flock -n /tmp/intellexia_kb.lock uv run scripts/process_knowledge_base.py --batch-size 10 >> /var/log/intellexia/process_knowledge_base.log 2>&1

# Processa análises de sentenças pendentes (a cada 3 minutos)
*/3 * * * * cd /opt/intellexia && flock -n /tmp/intellexia_sentence.lock uv run scripts/process_judicial_sentence_analysis.py >> /var/log/intellexia/process_judicial_sentence_analysis.log 2>&1

# Processa recursos judiciais pendentes (a cada 4 minutos)
*/4 * * * * cd /opt/intellexia && flock -n /tmp/intellexia_appeals.lock uv run scripts/process_judicial_appeals.py >> /var/log/intellexia/process_judicial_appeals.log 2>&1
```

## 3) Verificação rápida

Após salvar o crontab:

```bash
crontab -l
```

Acompanhe logs em tempo real:

```bash
tail -f /var/log/intellexia/process_knowledge_base.log
```

```bash
tail -f /var/log/intellexia/process_judicial_sentence_analysis.log
```

```bash
tail -f /var/log/intellexia/process_judicial_appeals.log
```

## 4) Observações importantes

- O uso de `flock -n` evita sobreposição de execuções quando um ciclo ainda está em andamento.
- Se o servidor não tiver `flock`, instale `util-linux` (Linux) ou substitua por outra estratégia de lock.
- Se quiser reprocessar erros da base de conhecimento, execute manualmente:

```bash
cd /opt/intellexia && uv run scripts/process_knowledge_base.py --include-errors --batch-size 20
```
