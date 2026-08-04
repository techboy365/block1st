/* ─────────────────────────────────────────────────────────────────
   Rydex Car Rental — script.js
───────────────────────────────────────────────────────────────── */

/* ── Mobile nav ─────────────────────────────────────────────────── */
const hamburger = document.getElementById('hamburger');
const mainNav   = document.getElementById('mainNav');
hamburger.addEventListener('click', () => {
  hamburger.classList.toggle('open');
  mainNav.classList.toggle('open');
});
mainNav.querySelectorAll('a').forEach(link => {
  link.addEventListener('click', () => {
    hamburger.classList.remove('open');
    mainNav.classList.remove('open');
  });
});

/* ── Booking tabs ───────────────────────────────────────────────── */
document.querySelectorAll('.btab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.btab').forEach(t => { t.classList.remove('active'); t.setAttribute('aria-selected','false'); });
    document.querySelectorAll('.tab-body').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    tab.setAttribute('aria-selected','true');
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
  });
});

/* ── Time dropdowns ─────────────────────────────────────────────── */
['pickupTime','returnTime'].forEach(id => {
  const sel = document.getElementById(id);
  if (!sel) return;
  for (let h = 0; h < 24; h++) {
    for (let m of [0,30]) {
      const o = document.createElement('option');
      o.value = o.textContent = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`;
      sel.appendChild(o);
    }
  }
});

/* ── Flatpickr ──────────────────────────────────────────────────── */
const today = new Date();
flatpickr('#pickupDate', {
  minDate: 'today', dateFormat: 'D, d M Y', defaultDate: today,
  onChange: ([d]) => {
    const next = new Date(d); next.setDate(next.getDate() + 3);
    ret.setDate(next); ret.set('minDate', d);
  }
});
const ret = flatpickr('#returnDate', {
  minDate: 'today', dateFormat: 'D, d M Y',
  defaultDate: new Date(today.getTime() + 3*86400000),
});

/* ── Search ─────────────────────────────────────────────────────── */
function handleSearch() {
  const pickup = document.getElementById('pickupLoc').value;
  const retn   = document.getElementById('returnLoc').value;
  const pd     = document.getElementById('pickupDate').value;
  const rd     = document.getElementById('returnDate').value;
  if (!pickup) { shake('pickupLoc'); return; }
  if (!retn)   { shake('returnLoc'); return; }
  if (!pd||!rd){ alert('Please select pick-up and return dates.'); return; }
  document.getElementById('fleet').scrollIntoView({ behavior:'smooth', block:'start' });
  setTimeout(() => {
    document.querySelectorAll('.car-card:not(.hidden)').forEach(c => {
      c.style.animation = 'none'; c.offsetHeight; c.style.animation = 'fadeUp .38s ease forwards';
    });
  }, 600);
}

function shake(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.animation = 'none'; el.offsetHeight; el.style.animation = 'shake .4s ease'; el.focus();
}

/* ── Fleet filter ───────────────────────────────────────────────── */
document.querySelectorAll('.fbtn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.fbtn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const f = btn.dataset.filter;
    document.querySelectorAll('.car-card').forEach(card => {
      const show = f === 'all' || card.dataset.category === f;
      card.classList.toggle('hidden', !show);
      if (show) { card.style.animation = 'none'; card.offsetHeight; card.style.animation = 'fadeUp .38s ease forwards'; }
    });
  });
});

/* ── Stats counter ──────────────────────────────────────────────── */
(function () {
  const els = document.querySelectorAll('.snum[data-target]');
  if (!els.length) return;
  let done = false;
  new IntersectionObserver(entries => {
    if (!entries[0].isIntersecting || done) return;
    done = true;
    els.forEach(el => {
      const t = parseFloat(el.dataset.target);
      const dec = !Number.isInteger(t);
      const suf = t >= 100 ? '+' : '';
      let v = 0; const inc = t / (1500 / 16);
      const ti = setInterval(() => {
        v = Math.min(v + inc, t);
        el.textContent = (dec ? v.toFixed(1) : Math.floor(v).toLocaleString()) + suf;
        if (v >= t) clearInterval(ti);
      }, 16);
    });
  }, { threshold: .4 }).observe(document.querySelector('.stats-row'));
})();

/* ── Modal ──────────────────────────────────────────────────────── */
function openModal()  { const m = document.getElementById('bModal'); m.style.display = 'flex'; document.body.style.overflow = 'hidden'; }
function closeModal() { const m = document.getElementById('bModal'); m.style.display = 'none'; document.body.style.overflow = ''; }
document.getElementById('bModal').addEventListener('click', e => { if (e.target.id === 'bModal') closeModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

/* ── Scroll top ─────────────────────────────────────────────────── */
const stBtn = document.createElement('button');
stBtn.className = 'scroll-top'; stBtn.setAttribute('aria-label', 'Back to top'); stBtn.textContent = '↑';
document.body.appendChild(stBtn);
window.addEventListener('scroll', () => stBtn.classList.toggle('visible', window.scrollY > 500));
stBtn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));

/* ── Reveal ─────────────────────────────────────────────────────── */
const ro = new IntersectionObserver(entries => entries.forEach(e => {
  if (e.isIntersecting) { e.target.classList.add('visible'); ro.unobserve(e.target); }
}), { threshold: .08 });
document.querySelectorAll('.reveal').forEach(el => ro.observe(el));

/* ── Keyframes ──────────────────────────────────────────────────── */
const s = document.createElement('style');
s.textContent = `
@keyframes fadeUp  { from{opacity:0;transform:translateY(18px)} to{opacity:1;transform:translateY(0)} }
@keyframes shake   { 0%,100%{transform:translateX(0)} 25%,75%{transform:translateX(-5px)} 50%{transform:translateX(5px)} }
`;
document.head.appendChild(s);
