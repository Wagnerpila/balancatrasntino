// Roda no "mundo" da própria página do WhatsApp, antes do código dele.
// Com a aba em segundo plano o Chrome não desenha a página (requestAnimationFrame para) e a
// prévia das imagens fica parada. Só enquanto a extensão está enviando (atributo
// data-balanca-enviando="1" no <html>), a aba se comporta como visível e os quadros de desenho
// andam a 1 por segundo. Fora do envio, nada muda.
(() => {
  const raiz = () => document.documentElement;
  const ativo = () => !!raiz() && raiz().dataset.balancaEnviando === '1';
  const pHidden = Object.getOwnPropertyDescriptor(Document.prototype, 'hidden');
  const pEstado = Object.getOwnPropertyDescriptor(Document.prototype, 'visibilityState');
  const escondida = () => pHidden.get.call(document);
  Object.defineProperty(document, 'hidden', {configurable: true, get: () => (ativo() ? false : escondida())});
  Object.defineProperty(document, 'visibilityState', {configurable: true,
    get: () => (ativo() ? 'visible' : pEstado.get.call(document))});

  const rafNativo = window.requestAnimationFrame.bind(window);
  const cafNativo = window.cancelAnimationFrame.bind(window);
  const fila = new Map();
  const canal = new MessageChannel();
  let seq = 0, marcado = false;
  // os quadros rodam a partir de uma mensagem (e não direto do relógio) para o Chrome não
  // tratar como relógio encadeado e atrasar para 1 por minuto
  canal.port1.onmessage = () => {
    marcado = false;
    const agora = performance.now(), cbs = [...fila.values()];
    fila.clear();
    for (const cb of cbs) {
      try { cb(agora); } catch (e) { setTimeout(() => { throw e; }); }
    }
  };
  window.requestAnimationFrame = cb => {
    if (!(ativo() && escondida())) return rafNativo(cb);
    const id = -(++seq);
    fila.set(id, cb);
    if (!marcado) {
      marcado = true;
      setTimeout(() => canal.port2.postMessage(0), 16);
    }
    return id;
  };
  window.cancelAnimationFrame = id => (id < 0 ? fila.delete(id) : cafNativo(id));

  // "Fotos e vídeos" do menu Anexar abre a janela do Windows para escolher arquivos (que não abre
  // com a aba em segundo plano). Com imagens deixadas pela extensão, entrega elas direto ao campo.
  let pendentes = null, pendentesAte = 0;
  window.addEventListener('message', e => {
    if (e.data && Array.isArray(e.data.balancaArquivos)) { pendentes = e.data.balancaArquivos; pendentesAte = Date.now() + 20000; }
  });
  const entregar = campo => {
    const dt = new DataTransfer();
    pendentes.forEach(f => dt.items.add(f));
    pendentes = null;
    campo.files = dt.files;
    campo.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const temPendentes = campo => campo.type === 'file' && pendentes && Date.now() < pendentesAte;
  const clickNativo = HTMLInputElement.prototype.click;
  HTMLInputElement.prototype.click = function () {
    if (temPendentes(this)) return entregar(this);
    return clickNativo.call(this);
  };
  if (HTMLInputElement.prototype.showPicker) {
    const pickerNativo = HTMLInputElement.prototype.showPicker;
    HTMLInputElement.prototype.showPicker = function () {
      if (temPendentes(this)) return entregar(this);
      return pickerNativo.call(this);
    };
  }

  // avisa o WhatsApp quando começa/termina o envio (ele relê a visibilidade)
  const observar = () => new MutationObserver(() => document.dispatchEvent(new Event('visibilitychange')))
    .observe(raiz(), {attributes: true, attributeFilter: ['data-balanca-enviando']});
  if (raiz()) observar(); else document.addEventListener('readystatechange', observar, {once: true});
})();
