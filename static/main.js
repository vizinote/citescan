const Lang = (() => {
  const params = new URLSearchParams(location.search);
  let lang = params.get('lang');
  if (!lang) {
    const nav = (navigator.language || navigator.languages?.[0] || 'en').toLowerCase();
    lang = nav.startsWith('fr') ? 'fr' : 'en';
  }
  localStorage.setItem('lang', lang);
  return localStorage.getItem('lang');
})();

async function loadTexts() {
  const resp = await fetch(`/textes/${Lang}.json`);
  if (!resp.ok) return;
  const t = await resp.json();
  document.documentElement.lang = Lang;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (t[key] !== undefined) {
      el.textContent = t[key];
    }
  });
  // Update switch link
  const sw = document.getElementById('lang-switch');
  if (sw && t.lang_switch) sw.textContent = t.lang_switch;
  if (sw) {
    const path = Lang === 'fr' ? '/fr/' : '/';
    sw.setAttribute('href', path + (Lang === 'fr' ? '?lang=' + Lang : '?lang=en'));
  }
}

document.getElementById('lang-switch').addEventListener('click', e => {
  const newLang = Lang === 'fr' ? 'en' : 'fr';
  localStorage.setItem('lang', newLang);
  // let link navigate; no need to prevent
});

// Scan logic
document.getElementById('scan-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const url = document.getElementById('url-input').value.trim();
  const btn = e.target.querySelector('button');
  const err = document.getElementById('error');
  const res = document.getElementById('result');
  err.hidden = true; res.hidden = true;

  let parsed;
  try { parsed = new URL(url); } catch { return; }
  if (!/^https?:/.test(parsed.protocol)) return;

  btn.disabled = true; btn.textContent = '…';
  try {
    const resp = await fetch(`/api/scan?url=${encodeURIComponent(url)}`);
    const data = await resp.json();
    if (!resp.ok) {
      err.textContent = data.detail || 'Erreur';
      err.hidden = false;
      return;
    }
    document.getElementById('score').textContent = data.score;
    const ul = document.getElementById('findings');
    ul.innerHTML = '';
    for (const f of data.findings) {
      const li = document.createElement('li');
      const span = document.createElement('span');
      span.className = 'icon';
      span.textContent = f.status === 'pass' ? '✓' : f.status === 'warn' ? '!' : '✗';
      const text = document.createElement('span');
      text.className = f.status === 'pass' ? 'ok-text' : f.status === 'warn' ? 'warn-text' : 'fail-text';
      text.textContent = f.text;
      li.appendChild(span); li.appendChild(text);
      ul.appendChild(li);
    }
    res.hidden = false;
    const cta = document.querySelector('.cta');
    cta.href = '#';
  } catch {
    err.textContent = 'Impossible de joindre le site';
    err.hidden = false;
  } finally {
    btn.disabled = false;
    await loadTexts();
  }
});

loadTexts();
