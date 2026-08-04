/* ─────────────────────────────────────────────────────────────────
   Rydex Car Rental — script.js
───────────────────────────────────────────────────────────────── */

/* ── Sticky header elevation ───────────────────────────────────── */
const header = document.getElementById('siteHeader');
window.addEventListener('scroll', () => {
  header.classList.toggle('elevated', window.scrollY > 20);
});

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
document.querySelectorAll('.booking-tabs-bar .tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.booking-tabs-bar .tab').forEach(t => {
      t.classList.remove('active');
      t.setAttribute('aria-selected', 'false');
    });
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    tab.setAttribute('aria-selected', 'true');
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
  });
});

/* ── Populate time dropdowns ────────────────────────────────────── */
function populateTimes(selectId) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  for (let h = 0; h < 24; h++) {
    for (let m of [0, 30]) {
      const hh = String(h).padStart(2, '0');
      const mm = String(m).padStart(2, '0');
      const opt = document.createElement('option');
      opt.value = `${hh}:${mm}`;
      opt.textContent = `${hh}:${mm}`;
      sel.appendChild(opt);
    }
  }
}
populateTimes('pickupTime');
populateTimes('returnTime');

/* ── Flatpickr date pickers ─────────────────────────────────────── */
const today = new Date();
flatpickr('#pickupDate', {
  minDate: 'today',
  dateFormat: 'D, d M Y',
  defaultDate: today,
  disableMobile: false,
  onChange: ([date]) => {
    const next = new Date(date);
    next.setDate(next.getDate() + 3);
    returnPicker.setDate(next);
    returnPicker.set('minDate', date);
  }
});
const returnPicker = flatpickr('#returnDate', {
  minDate: 'today',
  dateFormat: 'D, d M Y',
  defaultDate: new Date(today.getTime() + 3 * 86400000),
  disableMobile: false,
});

/* ── Search handler ─────────────────────────────────────────────── */
function handleSearch() {
  const pickup   = document.getElementById('pickupLocation').value;
  const ret      = document.getElementById('returnLocation').value;
  const pickDate = document.getElementById('pickupDate').value;
  const retDate  = document.getElementById('returnDate').value;

  if (!pickup)  { shake('pickupLocation'); return; }
  if (!ret)     { shake('returnLocation'); return; }
  if (!pickDate || !retDate) { alert('Please select pick-up and return dates.'); return; }

  document.getElementById('fleet').scrollIntoView({ behavior: 'smooth', block: 'start' });
  setTimeout(() => {
    document.querySelectorAll('.car-card:not(.hidden)').forEach(card => {
      card.style.animation = 'none';
      card.offsetHeight;
      card.style.animation = 'fadeInUp 0.4s ease forwards';
    });
  }, 600);
}

function shake(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.animation = 'none';
  el.offsetHeight;
  el.style.animation = 'shake 0.4s ease';
  el.focus();
}

/* ── Fleet filter ───────────────────────────────────────────────── */
document.querySelectorAll('.filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const filter = btn.dataset.filter;
    document.querySelectorAll('.car-card').forEach(card => {
      const show = filter === 'all' || card.dataset.category === filter;
      card.classList.toggle('hidden', !show);
      if (show) {
        card.style.animation = 'none';
        card.offsetHeight;
        card.style.animation = 'fadeInUp 0.38s ease forwards';
      }
    });
  });
});

/* ── Reviews slider ─────────────────────────────────────────────── */
(function () {
  const track   = document.getElementById('reviewsTrack');
  const cards   = track ? track.querySelectorAll('.review-card') : [];
  const dotsEl  = document.getElementById('sliderDots');
  const prevBtn = document.getElementById('sliderPrev');
  const nextBtn = document.getElementById('sliderNext');
  if (!track || !cards.length) return;

  let perView = getPerView();
  let current = 0;
  const total = cards.length;
  const maxIdx = () => Math.max(0, total - perView);

  function getPerView() {
    return window.innerWidth <= 480 ? 1 : window.innerWidth <= 768 ? 1 : window.innerWidth <= 1024 ? 2 : 3;
  }

  function buildDots() {
    if (!dotsEl) return;
    dotsEl.innerHTML = '';
    for (let i = 0; i <= maxIdx(); i++) {
      const d = document.createElement('button');
      d.className = 'slider-dot' + (i === current ? ' active' : '');
      d.setAttribute('aria-label', `Review ${i + 1}`);
      d.addEventListener('click', () => goTo(i));
      dotsEl.appendChild(d);
    }
  }

  function goTo(idx) {
    current = Math.min(Math.max(idx, 0), maxIdx());
    const w = cards[0].getBoundingClientRect().width + 24;
    track.style.transform = `translateX(-${current * w}px)`;
    if (dotsEl) dotsEl.querySelectorAll('.slider-dot').forEach((d, i) => d.classList.toggle('active', i === current));
  }

  if (prevBtn) prevBtn.addEventListener('click', () => goTo(current - 1));
  if (nextBtn) nextBtn.addEventListener('click', () => goTo(current + 1));

  window.addEventListener('resize', () => {
    perView = getPerView();
    current = Math.min(current, maxIdx());
    buildDots();
    goTo(current);
  });

  buildDots();
  setInterval(() => goTo(current >= maxIdx() ? 0 : current + 1), 5500);
})();

/* ── Animated stats counter ─────────────────────────────────────── */
(function () {
  const statEls = document.querySelectorAll('.stat-number[data-target]');
  if (!statEls.length) return;
  let animated = false;

  function animateCounters() {
    if (animated) return;
    animated = true;
    statEls.forEach(el => {
      const target    = parseFloat(el.dataset.target);
      const isFloat   = !Number.isInteger(target);
      const duration  = 1600;
      const step      = 16;
      const increment = target / (duration / step);
      const suffix    = target >= 100 ? '+' : '';
      let current     = 0;

      const timer = setInterval(() => {
        current = Math.min(current + increment, target);
        el.textContent = isFloat
          ? current.toFixed(1) + suffix
          : Math.floor(current).toLocaleString() + suffix;
        if (current >= target) clearInterval(timer);
      }, step);
    });
  }

  const strip = document.querySelector('.stats-strip');
  if (strip) {
    new IntersectionObserver(entries => {
      if (entries[0].isIntersecting) { animateCounters(); }
    }, { threshold: 0.4 }).observe(strip);
  }
})();

/* ── Modal ──────────────────────────────────────────────────────── */
function openModal() {
  const modal = document.getElementById('bookingModal');
  modal.style.display = 'flex';
  document.body.style.overflow = 'hidden';
}
function closeModal() {
  const modal = document.getElementById('bookingModal');
  modal.style.display = 'none';
  document.body.style.overflow = '';
}
const modal = document.getElementById('bookingModal');
if (modal) {
  modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

/* ── Scroll-to-top ──────────────────────────────────────────────── */
const scrollBtn = document.createElement('button');
scrollBtn.className = 'scroll-top';
scrollBtn.setAttribute('aria-label', 'Back to top');
scrollBtn.innerHTML = '↑';
document.body.appendChild(scrollBtn);
window.addEventListener('scroll', () => {
  scrollBtn.classList.toggle('visible', window.scrollY > 500);
});
scrollBtn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));

/* ── Reveal on scroll ───────────────────────────────────────────── */
const revealEls = document.querySelectorAll(
  '.why-card, .car-card, .step, .contact-item, .review-card'
);
revealEls.forEach(el => {
  if (!el.classList.contains('reveal')) el.classList.add('reveal');
});
new IntersectionObserver(
  entries => entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
    }
  }),
  { threshold: 0.1 }
).observe(document.body);

const ro = new IntersectionObserver(
  entries => entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
      ro.unobserve(entry.target);
    }
  }),
  { threshold: 0.08 }
);
document.querySelectorAll('.reveal').forEach(el => ro.observe(el));

/* ── Keyframe injection ─────────────────────────────────────────── */
const style = document.createElement('style');
style.textContent = `
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(20px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes shake {
  0%,100% { transform: translateX(0); }
  20%,60% { transform: translateX(-5px); }
  40%,80% { transform: translateX(5px); }
}
`;
document.head.appendChild(style);
