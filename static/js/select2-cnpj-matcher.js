/**
 * Matcher do Select2 que permite pesquisar CNPJ com ou sem pontuação.
 *
 * Compara normalmente pelo texto (nome da empresa) e, quando o termo digitado
 * contém dígitos, também compara apenas os dígitos — ignorando ".", "/" e "-"
 * em ambos os lados. Assim "12.345.678", "12345678" e "12.345.678/0001-90"
 * encontram o mesmo estabelecimento.
 *
 * Uso: passar `matcher: window.cnpjSelect2Matcher` na configuração do select2.
 */
(function () {
  function onlyDigits(value) {
    return (value || '').replace(/\D/g, '');
  }

  window.cnpjSelect2Matcher = function (params, data) {
    // Sem termo digitado: mantém a opção visível.
    if ($.trim(params.term) === '') {
      return data;
    }
    // Opções sem texto não correspondem.
    if (typeof data.text === 'undefined') {
      return null;
    }

    var term = $.trim(params.term).toLowerCase();
    var text = data.text.toLowerCase();

    // Correspondência textual padrão (nome da empresa, CNPJ como exibido, etc.).
    if (text.indexOf(term) > -1) {
      return data;
    }

    // Correspondência por dígitos: com ou sem pontuação bate no mesmo CNPJ.
    var termDigits = onlyDigits(params.term);
    if (termDigits) {
      if (onlyDigits(data.text).indexOf(termDigits) > -1) {
        return data;
      }
    }

    return null;
  };
})();
