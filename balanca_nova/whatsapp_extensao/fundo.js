// Fala com o sistema da balança neste computador (a página do WhatsApp não pode chamar o 127.0.0.1 direto).
const SISTEMA = 'http://127.0.0.1:8090/api/';

chrome.runtime.onMessage.addListener((m, _de, responder) => {
  if (!m.caminho) return;
  const opcoes = m.corpo ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(m.corpo)} : {};
  fetch(SISTEMA + m.caminho, opcoes)
    .then(r => r.json())
    .then(responder)
    .catch(e => responder({erro: 'Sistema da balança fechado (' + e.message + ')'}));
  return true;  // resposta assíncrona
});

// Relógio: com a aba do WhatsApp em segundo plano o Chrome atrasa os relógios dela (até 1 vez
// por minuto). O fundo da extensão não sofre isso: a cada 2 s ele acorda a aba para conferir a fila.
const esperar = ms => new Promise(r => setTimeout(r, ms));
let rodando = false;
async function relogio() {
  if (rodando) return;
  rodando = true;
  try {
    for (;;) {
      const [aba] = await chrome.tabs.query({url: 'https://web.whatsapp.com/*'});
      if (aba) {
        try { await chrome.tabs.sendMessage(aba.id, {tipo: 'ciclo'}); } catch (e) { /* aba carregando */ }
      }
      await esperar(2000);
    }
  } finally {
    rodando = false;
  }
}
// se o Chrome desligar o fundo da extensão, o alarme liga de novo
chrome.alarms.create('balanca', {periodInMinutes: 0.5});
chrome.alarms.onAlarm.addListener(relogio);
chrome.runtime.onStartup.addListener(relogio);
chrome.runtime.onInstalled.addListener(relogio);
relogio();
