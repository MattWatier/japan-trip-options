/* Japan 2026 — options by hub.
   Static site: one fetch of data/trip.json, hash routing, no dependencies. */

const view = document.getElementById('view');
let DATA = null;

/* ------------------------------------------------------------------ helpers */

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// The blurbs come straight from Obsidian notes, so a little markdown leaks through.
const md = (s) => esc(s)
  .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  .replace(/\*(.+?)\*/g, '<em>$1</em>')
  .replace(/`(.+?)`/g, '<code>$1</code>');

const KIND_COLOR = {
  temple: '#b4402f', shrine: '#b4402f', castle: '#2f4858', garden: '#35604a',
  park: '#35604a', nature: '#35604a', hike: '#35604a', island: '#2f7d8c',
  viewpoint: '#4b7f6a', museum: '#9a7a2e', market: '#c2703a', onsen: '#3d6fa3',
  neighborhood: '#7b756a', 'theme-park': '#a3457d', tour: '#8a5a2b',
  workshop: '#8a5a2b', 'food-experience': '#c2703a', other: '#7b756a',
};
const kindColor = (k) => KIND_COLOR[k] || KIND_COLOR.other;

function timeLabel(h) {
  if (!h) return null;
  if (h >= 7) return 'full day';
  if (h >= 4) return 'half day';
  return Number.isInteger(h) ? `${h} h` : `${h} h`;
}

function thumb(image, kind, alt, cls = 'thumb') {
  if (image && image.src) {
    return `<img class="${cls}" src="${esc(image.src)}" alt="${esc(alt)}" loading="lazy" decoding="async">`;
  }
  return `<div class="${cls} thumb-ph" style="--k:${kindColor(kind)}" role="img"
    aria-label="No photo yet for ${esc(alt)}"><span>${esc(kind || 'option')}</span></div>`;
}

// The vault stores `indoor` as true/false/mixed, which means nothing to a reader.
const INDOOR = { true: 'indoors', false: 'outdoors', mixed: 'some of both' };

const SEASON = {
  good: ['good', 'Good in late May'],
  ok: ['', 'Fine in late May'],
  poor: ['warn', 'Poor timing in late May'],
  peak: ['warn', 'Peak season in late May'],
  unknown: [null, null],
};

function optionBadges(o, { compact = false } = {}) {
  const b = [];
  if (o.mustDo) b.push('<span class="badge must">Must do</span>');
  const t = timeLabel(o.hours);
  if (t) b.push(`<span class="badge time">${esc(t)}</span>`);
  if (!compact && o.kind) b.push(`<span class="badge">${esc(o.kind)}</span>`);
  if (o.car) b.push('<span class="badge warn">Car needed</span>');
  const [cls, label] = SEASON[o.seasonMay] || SEASON.unknown;
  if (!compact && cls !== null && label && o.seasonMay !== 'ok') {
    b.push(`<span class="badge ${cls}">${esc(label)}</span>`);
  }
  if (!compact && o.booking === 'advance') b.push('<span class="badge warn">Book ahead</span>');
  return b.join('');
}

function optionCard(o) {
  return `<button class="opt" type="button" data-opt="${esc(o.slug)}">
    ${thumb(o.image, o.kind, o.name)}
    <div class="body">
      <h4>${esc(o.name)}</h4>
      <p class="desc">${md(o.description)}</p>
      <div class="row">${optionBadges(o, { compact: true })}</div>
      <div class="where">${esc([o.city, o.region].filter(Boolean).join(' · '))}</div>
    </div>
  </button>`;
}

const byId = (slug) => DATA.options.find((o) => o.slug === slug);
const optionsFor = (pkg) => pkg.options.map((n) => DATA.options.find((o) => o.name === n)).filter(Boolean);
const allPackages = (hub) => [
  ...hub.packages.map((p) => ({ ...p, from: null })),
  ...hub.sideQuests.flatMap((s) => s.packages.map((p) => ({ ...p, from: s }))),
];

// A hub with no photo of its own borrows one from the best-known place it covers.
function hubHero(hub) {
  if (hub.image) return { src: hub.image };
  const mine = DATA.options.filter((o) => o.hub === hub.id && o.image);
  const pick = mine.find((o) => o.mustDo) || mine[0];
  return pick ? pick.image : null;
}

function hubStats(hub) {
  const pkgs = allPackages(hub);
  const names = new Set(pkgs.flatMap((p) => p.options));
  const loose = DATA.options.filter((o) => o.hub === hub.id && !names.has(o.name));
  return { pkgs, options: [...names].map((n) => DATA.options.find((o) => o.name === n)).filter(Boolean), loose };
}

/* --------------------------------------------------------------------- home */

function renderHome() {
  const c = DATA.counts;
  const groups = new Map();
  DATA.hubs.forEach((h) => {
    const key = h.track.id === 'common' ? 'Common spine' : h.track.title;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(h);
  });

  const card = (h) => {
    const s = hubStats(h);
    return `<a class="hubcard" href="#/hub/${encodeURIComponent(h.id)}">
      ${thumb(hubHero(h), 'neighborhood', h.title)}
      <div class="body">
        <h3>${esc(h.title)}</h3>
        <p class="blurb">${md(h.blurb)}</p>
        <div class="meta">
          <span class="badge">${s.pkgs.length} package${s.pkgs.length === 1 ? '' : 's'}</span>
          <span class="badge">${s.options.length + s.loose.length} options</span>
          ${h.sideQuests.length ? `<span class="badge">${h.sideQuests.length} day trips</span>` : ''}
        </div>
      </div>
    </a>`;
  };

  view.innerHTML = `
    <section class="hero">
      <h1>What there is to do, hub by hub</h1>
      <p>We sleep in a handful of towns and explore out from each one. Every card below is a
        <em>candidate</em>: what it is, roughly how long it eats, and whether the timing works in
        late May. Nothing is booked — this is here so everyone can weigh in.</p>
      <div class="stats">
        <div><b>${c.options}</b><span>options researched</span></div>
        <div><b>${c.hubs}</b><span>possible bases</span></div>
        <div><b>${c.packages}</b><span>day-plan packages</span></div>
      </div>
    </section>
    ${[...groups.entries()].map(([title, hubs]) => `
      <section>
        <div class="section-head">
          <h2>${esc(title)}</h2>
          <p>${title === 'Common spine'
            ? 'On the trip whichever way we go'
            : 'One of four ways the trip could end — we pick a single track'}</p>
        </div>
        <div class="hubgrid">${hubs.map(card).join('')}</div>
      </section>`).join('')}`;
}

/* ---------------------------------------------------------------- hub page */

function renderHub(id) {
  const hub = DATA.hubs.find((h) => h.id === id);
  if (!hub) return renderMissing();
  const s = hubStats(hub);

  const pkgBlock = (p) => {
    const opts = optionsFor(p);
    const sum = opts.reduce((a, o) => a + (o.hours || 0), 0);
    return `<details class="pkg">
      <summary>
        <svg class="caret" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M4 2l5 4-5 4z" fill="currentColor"/></svg>
        <div class="sum-main">
          <h3>${esc(p.title)}</h3>
          ${p.qualifier ? ` <span class="qual">— ${esc(p.qualifier)}</span>` : ''}
          <div class="sum-meta">
            ${p.checked ? '<span class="badge picked">Picked</span>' : ''}
            <span class="badge time">${p.hours} h budgeted</span>
            ${opts.length ? `<span class="badge">${opts.length} stop${opts.length === 1 ? '' : 's'}</span>` : ''}
            ${sum > p.hours + 0.01 ? `<span class="badge warn">stops add to ${+sum.toFixed(1)} h — pick some</span>` : ''}
            ${p.from ? `<span class="badge track">day trip · ${esc(p.from.label)}</span>` : ''}
            ${p.tags.slice(0, 3).map((t) => `<span class="badge">${esc(t)}</span>`).join('')}
          </div>
        </div>
      </summary>
      <div class="inner">
        ${p.note ? `<p class="note">${md(p.note)}</p>` : ''}
        ${opts.length
          ? `<div class="optgrid">${opts.map(optionCard).join('')}</div>`
          : '<p class="empty">No individual stops attached yet — this one is a single block of time (a tour, a transfer, or a whole day in one place).</p>'}
      </div>
    </details>`;
  };

  const inCity = s.pkgs.filter((p) => !p.from);
  const trips = hub.sideQuests
    .map((sq) => ({ sq, pkgs: s.pkgs.filter((p) => p.from && p.from.id === sq.id) }))
    .filter((g) => g.pkgs.length);

  view.innerHTML = `
    <a class="backlink" href="#/">← All hubs</a>
    <section class="hubhero">
      <div>
        <h1>${esc(hub.title)}</h1>
        <p class="blurb">${md(hub.blurb)}</p>
        <div class="meta">
          <span class="badge track">${esc(hub.track.id === 'common' ? 'Common spine' : hub.track.title)}</span>
          <span class="badge">${hub.minNights}+ nights</span>
          <span class="badge">${s.pkgs.length} packages</span>
          <span class="badge">${s.options.length + s.loose.length} options</span>
        </div>
      </div>
      <div class="order-img">${thumb(hubHero(hub), 'neighborhood', hub.title, 'thumb')}</div>
    </section>
    ${hub.map ? `<figure class="locator">
      <img src="${esc(hub.map)}" alt="Where ${esc(hub.label)} sits on a map of Japan" loading="lazy">
      <figcaption>Where it sits in Japan</figcaption>
    </figure>` : ''}

    <div class="section-head">
      <h2>Day plans in ${esc(hub.label)}</h2>
      <p>Open one to see the individual stops</p>
    </div>
    ${inCity.length ? inCity.map(pkgBlock).join('') : '<p class="muted">No in-city packages yet.</p>'}

    ${trips.map((g) => `
      <div class="section-head">
        <h2>${esc(g.sq.title)}</h2>
        <p>Day trip from ${esc(hub.label)}</p>
      </div>
      ${g.sq.blurb ? `<p class="muted" style="max-width:70ch;margin-top:-6px">${md(g.sq.blurb)}</p>` : ''}
      ${g.pkgs.map(pkgBlock).join('')}`).join('')}

    ${s.loose.length ? `
      <div class="section-head">
        <h2>Also researched here</h2>
        <p>Not attached to a day plan yet</p>
      </div>
      <div class="optgrid">${s.loose.map(optionCard).join('')}</div>` : ''}`;

  window.scrollTo(0, 0);
}

/* -------------------------------------------------------------- all options */

const filters = { q: '', hub: '', kind: '', time: '', must: false, walkin: false, nocar: false };

function matches(o) {
  const f = filters;
  if (f.hub && o.hub !== f.hub) return false;
  if (f.kind && o.kind !== f.kind) return false;
  if (f.must && !o.mustDo) return false;
  if (f.walkin && o.booking === 'advance') return false;
  if (f.nocar && o.car) return false;
  if (f.time === 'short' && !(o.hours && o.hours <= 2)) return false;
  if (f.time === 'half' && !(o.hours > 2 && o.hours < 7)) return false;
  if (f.time === 'full' && !(o.hours >= 7)) return false;
  if (f.q) {
    const hay = `${o.name} ${o.description} ${o.city} ${o.region} ${o.kind} ${o.category}`.toLowerCase();
    if (!f.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w))) return false;
  }
  return true;
}

function renderAll() {
  const kinds = [...new Set(DATA.options.map((o) => o.kind))].sort();
  view.innerHTML = `
    <section class="hero" style="padding-bottom:6px">
      <h1>Every option</h1>
      <p>All ${DATA.counts.options} candidates across every hub. Filter by how much of a day
        you want to give up, or search for something specific.</p>
    </section>
    <div class="controls">
      <label class="search">
        <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="2"/>
          <path d="M11 11l4 4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        <input type="search" id="q" placeholder="Search options, cities, kinds…"
          aria-label="Search options" value="${esc(filters.q)}">
      </label>
      <div class="filterbar">
        <select id="f-hub" aria-label="Filter by hub">
          <option value="">All hubs</option>
          ${DATA.hubs.map((h) => `<option value="${esc(h.id)}">${esc(h.label)}</option>`).join('')}
        </select>
        <select id="f-kind" aria-label="Filter by kind">
          <option value="">Any kind</option>
          ${kinds.map((k) => `<option value="${esc(k)}">${esc(k)}</option>`).join('')}
        </select>
        <select id="f-time" aria-label="Filter by time needed">
          <option value="">Any length</option>
          <option value="short">Under 2 hours</option>
          <option value="half">Half day</option>
          <option value="full">Full day</option>
        </select>
        <span class="sep"></span>
        <button class="chip" id="f-must" type="button" aria-pressed="false">Must do</button>
        <button class="chip" id="f-walkin" type="button" aria-pressed="false">No booking needed</button>
        <button class="chip" id="f-nocar" type="button" aria-pressed="false">No car</button>
      </div>
    </div>
    <p class="resultline" id="count"></p>
    <div class="optgrid" id="results"></div>`;

  ['hub', 'kind', 'time'].forEach((k) => {
    const el = document.getElementById(`f-${k}`);
    el.value = filters[k];
    el.onchange = () => { filters[k] = el.value; paint(); };
  });
  ['must', 'walkin', 'nocar'].forEach((k) => {
    const el = document.getElementById(`f-${k}`);
    el.setAttribute('aria-pressed', String(filters[k]));
    el.onclick = () => { filters[k] = !filters[k]; el.setAttribute('aria-pressed', String(filters[k])); paint(); };
  });
  const q = document.getElementById('q');
  q.oninput = () => { filters.q = q.value; paint(); };

  function paint() {
    const hits = DATA.options.filter(matches);
    document.getElementById('count').textContent =
      `${hits.length} of ${DATA.options.length} options`;
    document.getElementById('results').innerHTML = hits.length
      ? hits.map(optionCard).join('')
      : '<p class="empty-state">Nothing matches those filters. Try loosening one.</p>';
  }
  paint();
}

function renderMissing() {
  view.innerHTML = `<p class="empty-state">That page doesn't exist. <a href="#/">Back to the hubs</a>.</p>`;
}

/* ------------------------------------------------------------------ dialog */

function openOption(slug) {
  const o = byId(slug);
  if (!o) return;
  const img = o.image;
  const rows = [
    ['Where', [o.city, o.region].filter(Boolean).join(' · ')],
    ['Time needed', o.hours ? `${o.hours} h${timeLabel(o.hours) !== `${o.hours} h` ? ` (${timeLabel(o.hours)})` : ''}` : ''],
    ['Effort', o.effort],
    ['Indoors?', INDOOR[o.indoor] || ''],
    ['Booking', o.booking === 'advance' ? 'Book in advance' : o.booking],
    ['Closed', o.closedDays],
    ['Cost', o.costJpy ? `about ¥${Number(o.costJpy).toLocaleString()} pp` : ''],
    ['From the hub', o.transitMin ? `about ${o.transitMin} min` : ''],
    ['Late May', (SEASON[o.seasonMay] || [])[1]],
    ['Part of', o.packages.map((p) => p.split(' :: ').pop()).join(', ')],
  ].filter(([, v]) => v);

  const dlg = document.createElement('dialog');
  dlg.innerHTML = `
    <button class="dlg-close" type="button" aria-label="Close">×</button>
    ${img && img.src ? `<img class="hero" src="${esc(img.src)}" alt="${esc(o.name)}">` : ''}
    <div class="dlg-body">
      <h2>${esc(o.name)}</h2>
      <p class="where">${esc([o.city, o.region].filter(Boolean).join(' · '))}</p>
      <div class="meta">${optionBadges(o)}</div>
      <p class="desc">${md(o.description)}</p>
      ${o.flag ? `<p class="flag">${md(o.flag)}</p>` : ''}
      <dl class="dl">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>
      <div class="dlg-links">
        ${o.maps ? `<a class="btn" href="${esc(o.maps)}" target="_blank" rel="noopener">Open in Maps</a>` : ''}
        ${o.url ? `<a class="btn ghost" href="${esc(o.url)}" target="_blank" rel="noopener">More info</a>` : ''}
      </div>
    </div>
    ${img && img.artist ? `<p class="credit">Photo: ${md(img.artist)} —
      <a href="${esc(img.page)}" target="_blank" rel="noopener">${esc(img.license || 'Wikimedia Commons')}</a>
      · matched to this place from ${esc(img.distanceM)} m away</p>` : ''}`;

  document.body.appendChild(dlg);
  dlg.querySelector('.dlg-close').onclick = () => dlg.close();
  dlg.addEventListener('close', () => dlg.remove());
  dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
  dlg.showModal();
}

document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-opt]');
  if (btn) openOption(btn.dataset.opt);
});

/* ------------------------------------------------------------------ routing */

function route() {
  if (!DATA) return;
  const hash = location.hash.replace(/^#/, '') || '/';
  const [, section, arg] = hash.split('/');
  document.querySelectorAll('[data-nav]').forEach((a) => a.removeAttribute('aria-current'));
  if (section === 'hub' && arg) {
    renderHub(decodeURIComponent(arg));
  } else if (section === 'all') {
    document.querySelector('[data-nav="all"]').setAttribute('aria-current', 'page');
    renderAll();
  } else {
    document.querySelector('[data-nav="home"]').setAttribute('aria-current', 'page');
    renderHome();
  }
}
window.addEventListener('hashchange', route);

/* -------------------------------------------------------------------- theme */

const themeBtn = document.getElementById('theme');
const saved = localStorage.getItem('theme');
if (saved) document.documentElement.dataset.theme = saved;
else if (matchMedia('(prefers-color-scheme: dark)').matches) document.documentElement.dataset.theme = 'dark';
themeBtn.onclick = () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('theme', next);
};

/* --------------------------------------------------------------------- boot */

fetch('data/trip.json')
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then((d) => {
    DATA = d;
    document.getElementById('footer-meta').textContent =
      `${d.counts.options} options · ${d.counts.packages} packages · ${d.counts.withPhoto} with photos · exported ${d.generated} from the planning vault.`;
    route();
  })
  .catch(() => {
    view.innerHTML = `<div class="empty-state">
      <p><strong>Couldn't load the trip data.</strong></p>
      <p>If you opened this file directly from disk, browsers block the data fetch.
      Serve the folder instead:</p>
      <p><code>python3 -m http.server</code> then open <code>localhost:8000</code>.</p>
    </div>`;
  });
