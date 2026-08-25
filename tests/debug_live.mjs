// Debug helper: why doesn't live mode engage under jsdom?
import { JSDOM } from 'jsdom';

const BASE = 'http://localhost:8123';
const html = await (await fetch(BASE + '/')).text();
const errors = [];
const dom = new JSDOM(html, {
  url: BASE + '/',
  runScripts: 'dangerously',
  pretendToBeVisual: true,
  beforeParse(w) {
    w.fetch = (i, init) => fetch(new URL(String(i), BASE).href, init);
    w.addEventListener('error', (e) => errors.push('window error: ' + e.message));
  },
});
const liveSrc = await (await fetch(BASE + '/live.js')).text();
try {
  dom.window.eval(liveSrc);
  errors.push('live.js eval: no throw');
} catch (e) {
  errors.push('live.js eval THREW: ' + e.message);
}
await new Promise((r) => setTimeout(r, 3000));
errors.push('__ATLAS_LIVE__ = ' + dom.window.__ATLAS_LIVE__);
errors.push('edition = ' +
  dom.window.document.querySelector('.edition').textContent);
console.log(errors.join('\n'));
process.exit(0);
