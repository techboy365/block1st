/* ─────────────────────────────────────────────────────────────
   Rydex Car Rental — script.js
───────────────────────────────────────────────────────────── */

/* Mobile nav */
const burger  = document.getElementById('burger');
const mainNav = document.getElementById('mainNav');
burger.addEventListener('click', () => { burger.classList.toggle('open'); mainNav.classList.toggle('open'); });
mainNav.querySelectorAll('a').forEach(a => a.addEventListener('click', () => { burger.classList.remove('open'); mainNav.classList.remove('open'); }));

/* Booking tabs */
document.querySelectorAll('.btab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.btab').forEach(t => { t.classList.remove('active'); t.setAttribute('aria-selected','false'); });
    document.querySelectorAll('.tab-body').forEach(p => p.classList.remove('active'));
    tab.classList.add('active'); tab.setAttribute('aria-selected','true');
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
  });
});

/* Time dropdowns */
['pt','rt'].forEach(id => {
  const s = document.getElementById(id); if (!s) return;
  for (let h = 0; h < 24; h++) for (let m of [0,30]) {
    const o = document.createElement('option');
    o.value = o.textContent = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`;
    s.appendChild(o);
  }
});

/* Flatpickr */
const today = new Date();
flatpickr('#pd', { minDate:'today', dateFormat:'D, d M Y', defaultDate:today,
  onChange([d]) { const nx = new Date(d); nx.setDate(nx.getDate()+3); rp.setDate(nx); rp.set('minDate',d); }
});
const rp = flatpickr('#rd', { minDate:'today', dateFormat:'D, d M Y', defaultDate:new Date(today.getTime()+3*864e5) });

/* Search */
function handleSearch() {
  const p = document.getElementById('ploc').value;
  const r = document.getElementById('rloc').value;
  const pd = document.getElementById('pd').value;
  const rd = document.getElementById('rd').value;
  if (!p) { shake('ploc'); return; }
  if (!r) { shake('rloc'); return; }
  if (!pd||!rd) { alert('Please select pick-up and return dates.'); return; }
  document.getElementById('fleet').scrollIntoView({behavior:'smooth',block:'start'});
  setTimeout(() => document.querySelectorAll('.car-card:not(.hidden)').forEach(c => {
    c.style.animation='none'; c.offsetHeight; c.style.animation='fu .35s ease forwards';
  }), 600);
}
function shake(id) {
  const el = document.getElementById(id); if (!el) return;
  el.style.animation='none'; el.offsetHeight; el.style.animation='shk .38s ease'; el.focus();
}

/* Fleet filter */
document.querySelectorAll('.fbtn').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.fbtn').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  const f = b.dataset.filter;
  document.querySelectorAll('.car-card').forEach(c => {
    const show = f==='all' || c.dataset.category===f;
    c.classList.toggle('hidden', !show);
    if (show) { c.style.animation='none'; c.offsetHeight; c.style.animation='fu .35s ease forwards'; }
  });
}));

/* Stats counter */
(function(){
  const els = document.querySelectorAll('.snum[data-target]'); if (!els.length) return;
  let done = false;
  new IntersectionObserver(entries => {
    if (!entries[0].isIntersecting||done) return; done=true;
    els.forEach(el => {
      const t=parseFloat(el.dataset.target), dec=!Number.isInteger(t), suf=t>=100?'+':'';
      let v=0; const inc=t/(1400/16);
      const ti=setInterval(()=>{ v=Math.min(v+inc,t); el.textContent=(dec?v.toFixed(1):Math.floor(v).toLocaleString())+suf; if(v>=t)clearInterval(ti); },16);
    });
  },{threshold:.4}).observe(document.querySelector('.stats-row'));
})();

/* Modal */
function openModal()  { const m=document.getElementById('bModal'); m.style.display='flex'; document.body.style.overflow='hidden'; }
function closeModal() { const m=document.getElementById('bModal'); m.style.display='none'; document.body.style.overflow=''; }
document.getElementById('bModal').addEventListener('click', e => { if(e.target.id==='bModal') closeModal(); });
document.addEventListener('keydown', e => { if(e.key==='Escape') closeModal(); });

/* Scroll top */
const st = document.createElement('button');
st.className='scroll-top'; st.setAttribute('aria-label','Back to top'); st.textContent='↑';
document.body.appendChild(st);
window.addEventListener('scroll', () => st.classList.toggle('vis', window.scrollY>450));
st.addEventListener('click', () => window.scrollTo({top:0,behavior:'smooth'}));

/* Reveal */
const ro = new IntersectionObserver(entries => entries.forEach(e => {
  if (e.isIntersecting) { e.target.classList.add('vis'); ro.unobserve(e.target); }
}), {threshold:.08});
document.querySelectorAll('.reveal').forEach(el => ro.observe(el));

/* Keyframes */
const sty = document.createElement('style');
sty.textContent=`
@keyframes fu  { from{opacity:0;transform:translateY(16px)} to{opacity:1;transform:translateY(0)} }
@keyframes shk { 0%,100%{transform:translateX(0)} 25%,75%{transform:translateX(-5px)} 50%{transform:translateX(5px)} }
`;
document.head.appendChild(sty);
