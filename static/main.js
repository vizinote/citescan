const Lang = (() => {
  // The URL path decides: /fr/ = French, everything else = English (hreflang
  // semantics). Only an explicit ?lang=fr|en overrides. localStorage is NOT
  // consulted: it used to win over the path, so clicking "Français"/"English"
  // after a visit in the other language kept the page in the wrong language
  // (bug recette 2026-08-24).
  const params = new URLSearchParams(location.search);
  let lang = params.get('lang');
  if (lang !== 'fr' && lang !== 'en') {
    lang = location.pathname.startsWith('/fr') ? 'fr' : 'en';
  }
  localStorage.setItem('lang', lang);
  return lang;
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
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    if (t[key] !== undefined) {
      el.setAttribute('placeholder', t[key]);
    }
  });
  // Update switch link: point to the OTHER language page
  const sw = document.getElementById('lang-switch');
  if (sw) {
    const other = Lang === 'fr' ? 'en' : 'fr';
    if (t.lang_switch) sw.textContent = t.lang_switch;
    sw.setAttribute('href', other === 'fr' ? '/fr/' : '/');
  }
  return t;
}

// Scan logic
document.getElementById('scan-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const rawUrl = document.getElementById('url-input').value.trim();
  const btn = e.target.querySelector('button');
  const err = document.getElementById('error');
  const res = document.getElementById('result');
  err.hidden = true; res.hidden = true;

  const t = await loadTexts() || {};
  // Normalize: accept bare domains ("example.com" -> "https://example.com")
  let url = rawUrl;
  if (!/^https?:\/\//i.test(url)) url = 'https://' + url;
  let parsed;
  try { parsed = new URL(url); } catch {
    err.textContent = t.form_error_invalid || 'Invalid URL';
    err.hidden = false;
    return;
  }
  if (!parsed.hostname || !parsed.hostname.includes('.')) {
    err.textContent = t.form_error_invalid || 'Invalid URL';
    err.hidden = false;
    return;
  }

  btn.disabled = true;
  btn.textContent = t.scan_analyzing || '…';
  try {
    const resp = await fetch(`/api/scan?url=${encodeURIComponent(url)}&lang=${Lang}`);
    const data = await resp.json();
    if (!resp.ok) {
      err.textContent = resp.status === 429
        ? (t.form_error_rate || data.detail)
        : (t.form_error_network || data.detail || 'Error');
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
    err.textContent = t.form_error_network || 'Network error';
    err.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = t.scan_button || 'Scan';
  }
});

loadTexts();
