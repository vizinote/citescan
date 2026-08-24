// Simule la detection de langue de main.js dans plusieurs scenarios.
// Usage: node check_lang.js  (execute depuis la racine du repo)
const fs = require("fs");
const src = fs.readFileSync("static/main.js", "utf8");
const iife = src.match(/const Lang = \(\(\) => \{[\s\S]*?\}\)\(\);/)[0];

function scenario(path, search, saved) {
  const localStorage = { _v: saved, getItem(k){ return this._v; }, setItem(k,v){ this._v = v; } };
  const location = { pathname: path, search };
  const fn = new Function("location", "localStorage", "URLSearchParams",
    iife.replace("const Lang =", "return"));
  return fn(location, localStorage, URLSearchParams);
}

const cases = [
  ["bug recette: /fr/ apres visite EN", "/fr/", "", "en", "fr"],
  ["/fr/ frais", "/fr/", "", null, "fr"],
  ["/ apres visite FR", "/", "", "fr", "en"],
  ["/ frais", "/", "", null, "en"],
  ["?lang=fr explicite sur /", "/", "?lang=fr", null, "fr"],
  ["?lang invalide sur /fr/", "/fr/", "?lang=xx", null, "fr"],
];
let fail = 0;
for (const [name, p, s, saved, want] of cases) {
  const got = scenario(p, s, saved);
  const ok = got === want;
  if (!ok) fail++;
  console.log(`${ok ? "PASS" : "FAIL"} ${name} -> ${got} (attendu ${want})`);
}
process.exit(fail ? 1 : 0);
