# Avatar do usuário na header a partir do login com Google

**Data:** 2026-08-11
**Objetivo:** exibir a foto de perfil do Google no avatar do usuário na header, substituindo a inicial em círculo quando houver foto — sem depender de upload manual nem de storage local.

## Contexto

O escopo OAuth já pedido em `app/services/google_oauth.py` é `openid email profile`, e o `profile` faz o Google devolver a claim `picture` no `userinfo` — uma URL pública no CDN dele (`https://lh3.googleusercontent.com/a/...=s96-c`). Hoje essa claim é descartada em `auth.google_callback`.

O avatar atual é a inicial do nome em círculo, renderizada em **dois pontos** de `templates/partials/header.html`: o chip do navbar (pequeno) e o cabeçalho do dropdown do usuário (90px). Nenhum outro template usa avatar.

Não há Content-Security-Policy na aplicação, então referenciar o CDN do Google direto no `src` funciona sem ajuste de header HTTP.

## Decisões

- **Persistir no usuário, não só na sessão.** Nova coluna `users.google_picture_url` (`VARCHAR(512)`, nullable). Sem ela, quem entrasse por senha voltaria à inicial em círculo — as duas portas de login divergiriam, que é justamente o que `_start_user_session` existe para evitar.
- **Hotlink do CDN do Google, sem cópia local.** Zero storage, zero rota nova, foto sempre atual. O custo é depender de um domínio externo; coberto pelo fallback (abaixo). Baixar e servir localmente exigiria download no caminho do login, storage por escritório, rota autenticada de serving e invalidação — desproporcional para um avatar de 32px.
- **A URL é sanitizada antes de ser gravada.** Ela termina num `src` de `<img>` renderizado para o usuário; o `id_token` é assinado pelo Google, mas a checagem custa três linhas.
- **A cada login com Google o campo é reescrito com o que vier, inclusive `None`.** Se a pessoa remover a foto no Google, ela some aqui também. Login por senha nunca toca no campo.
- **Fallback sempre presente no HTML.** A inicial em círculo continua no DOM, escondida, e assume no `onerror` do `<img>`. É o único jeito de cobrir URL que virou 404 (foto trocada entre logins) ou rede do escritório que bloqueia `googleusercontent.com` — nunca fica ícone quebrado.

## Alterações

### 1. Schema

`app/models.py` — `User`, junto do bloco de login com Google:

```python
google_picture_url = db.Column(db.String(512), nullable=True)
```

Migration standalone `database/add_google_picture_to_users.py`, no padrão do projeto: roda dentro de `with app.app_context():`, verifica a existência da coluna antes de criar (idempotente), mensagens claras de sucesso e erro.

### 2. Sanitizador

`app/services/google_oauth.py` — função nova, pura, sem rede:

```python
def sanitize_picture_url(raw):
    """Só https em host do Google — a URL vai direto para o src de um <img>."""
```

Aceita apenas esquema `https` e host igual a `googleusercontent.com` ou terminado em `.googleusercontent.com`. Qualquer outra coisa (vazio, `http://`, `javascript:`, host de terceiro) devolve `None`.

### 3. Captura no callback

`app/blueprints/auth.py::google_callback` — ao lado da leitura de `sub` e `email`:

```python
picture = sanitize_picture_url(claims.get('picture'))
```

Atribuição direta no callback (`user.google_picture_url = picture`), logo após `_link_google_account(user, google_sub)` — mesma transação, o commit continua sendo o do `_start_user_session`, sem commit extra. `_link_google_account` não muda de assinatura: ele cuida do vínculo do `sub`, que tem regra própria (desvincular o `sub` de outro usuário antes de gravar); a foto é atribuição simples e não pertence lá.

### 4. Sessão

`app/blueprints/auth.py::_start_user_session` — fonte única das duas portas de login:

```python
session['user_picture'] = user.google_picture_url
```

Lê do model, então vale para login por senha também. O header não faz query por request. Sessões já abertas não têm a chave; `session.get('user_picture')` devolve `None` e o fallback assume.

### 5. Template

Macro nova `templates/partials/user_avatar.html`:

```jinja
{% macro user_avatar(size, font_size, extra_classes='') %}
```

Renderiza os dois elementos irmãos: o `<img>` (só quando há `session['user_picture']`) e o `<span>` da inicial. Quando há foto, o `<span>` sai com `display:none` e o `<img>` traz `onerror` que esconde a si mesmo e revela o irmão. Sem foto, só o `<span>` é renderizado.

Ambos recebem `extra_classes` e o mesmo `width`/`height`/`font-size` inline vindos dos parâmetros, para que a troca no `onerror` não mude o tamanho. Atributos extras do `<img>`: `referrerpolicy="no-referrer"` e `alt=""` (decorativo — o nome do usuário já aparece ao lado). As classes de forma atuais (`rounded-circle shadow`) ficam dentro da macro.

`templates/partials/header.html` importa a macro e a usa nos dois pontos existentes:

- **Chip do navbar** — `size=32`, `font_size=14`, `extra_classes='user-image ...'`. O AdminLTE já define `.navbar-nav > .user-menu .user-image` como `2rem × 2rem` (= 32px) mais `float`/`margin`, então passar a classe preserva o espaçamento e o tamanho inline bate com o atual: nenhuma mudança visual para quem não tem foto.
- **Cabeçalho do dropdown** — `size=90`, `font_size=32`, sem `extra_classes`.

Nenhum outro template muda.

### 6. Documentação

Parágrafo na seção "Login com Google" do `CLAUDE.md`: a claim `picture` é gravada em `users.google_picture_url` a cada login com Google, exibida via hotlink do CDN e com fallback para a inicial em círculo.

## Testes

Script standalone `tests/test_google_avatar.py`, no padrão de `tests/` (importa `main.app`, usa `app.test_client()`):

1. `sanitize_picture_url` — URL do Google passa; `http://`, `javascript:`, host de terceiro, string vazia e `None` devolvem `None`.
2. Render do header com `user_picture` na sessão — a resposta contém o `<img>` apontando para a URL.
3. Render do header sem `user_picture` — a resposta traz a inicial em círculo e nenhum `<img>` de avatar.

## Fora de escopo

- Upload manual de foto na tela de Perfil.
- Avatar em outras telas (Atividade de Usuários, comentários de caso) — a macro fica disponível para isso depois.
- Sincronizar a foto fora do momento do login.
- Cópia local da imagem / proxy de avatar.
