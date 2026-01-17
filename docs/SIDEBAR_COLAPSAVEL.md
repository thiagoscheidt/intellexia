# Funcionalidade de Sidebar Colapsável

## Descrição

A sidebar agora possui funcionalidade de colapsar/expandir, oferecendo três modos de visualização:

### Modos de Visualização

1. **Expandida (Padrão)**: Sidebar totalmente aberta mostrando ícones e textos
2. **Colapsada**: Sidebar mostra apenas os ícones (largura reduzida)
3. **Colapsada com Hover**: Quando colapsada, expande temporariamente ao passar o mouse

## Como Usar

### Botões no Header

- **Botão de Lista (☰)**: Toggle rápido - abre/fecha a sidebar completamente
- **Botão de Pin (📌)**: Fixa ou desafixa a sidebar no estado colapsado
  - Ícone normal: Sidebar está expandida e fixada
  - Ícone preenchido: Sidebar está colapsada e pode expandir no hover

### Comportamento

#### Estado Expandido (Fixado)
- Sidebar totalmente visível com textos
- Ocupa ~250px de largura
- Não colapsa ao passar o mouse

#### Estado Colapsado
- Sidebar mostra apenas ícones
- Ocupa ~4.6rem (~73px) de largura
- Expande temporariamente ao passar o mouse sobre ela
- Mostra tooltips ao lado dos ícones quando não está expandida no hover
- Estado é salvo no localStorage do navegador

### Recursos

- ✅ Transições suaves entre estados
- ✅ Tooltips automáticos quando colapsada
- ✅ Estado persistente (salvo no navegador)
- ✅ Expansão temporária no hover quando colapsada
- ✅ Design responsivo
- ✅ Compatível com AdminLTE e Bootstrap

## Implementação Técnica

### Arquivos Modificados

1. **templates/layout/base.html**
   - Adicionado CSS customizado para transições e comportamento
   - Adicionado JavaScript para controle de estado e hover
   - Removida classe `sidebar-open` padrão

2. **templates/partials/header.html**
   - Adicionado botão de pin/unpin
   - Melhorado tooltip do botão de toggle

3. **templates/partials/sidebar.html**
   - Adicionados atributos `title` nos links principais para tooltips

### Classes CSS Utilizadas

- `.sidebar-collapse`: Sidebar está colapsada
- `.sidebar-hover`: Sidebar está expandida temporariamente no hover
- `.sidebar-open`: Sidebar está totalmente aberta e fixada

### LocalStorage

O estado da sidebar é salvo em:
```javascript
localStorage.setItem('sidebarPinned', 'true|false')
```

Isso garante que a preferência do usuário seja mantida entre sessões.

## Compatibilidade

- ✅ Bootstrap 5
- ✅ AdminLTE 4
- ✅ Navegadores modernos (Chrome, Firefox, Safari, Edge)
- ✅ Responsivo (mobile e desktop)
