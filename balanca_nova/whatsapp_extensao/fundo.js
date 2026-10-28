// Fala com o sistema da balança neste computador (a página do WhatsApp não pode chamar o 127.0.0.1 direto).
const SISTEMA = 'http://127.0.0.1:8090/api/';

chrome.runtime.onMessage.addListener((m, _de, responder) => {
  const opcoes = m.corpo ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(m.corpo)} : {};
  fetch(SISTEMA + m.caminho, opcoes)
    .then(r => r.json())
    .then(responder)
    .catch(e => responder({erro: 'Sistema da balança fechado (' + e.message + ')'}));
  return true;  // resposta assíncrona
});
