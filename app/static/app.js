/* 아마도 경제 — 테마 전환 · 리빌 · 실시간 쿨다운 · AJAX 액션. */
(function () {
  'use strict';

  var root = document.documentElement;
  root.classList.add('js');

  /* ---------- 테마 전환 ---------- */
  var opts = Array.prototype.slice.call(document.querySelectorAll('.theme-opt'));
  function applyTheme(name) {
    root.setAttribute('data-theme', name);
    try { localStorage.setItem('theme', name); } catch (e) {}
    opts.forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-theme') === name);
    });
  }
  function currentTheme() { try { return localStorage.getItem('theme'); } catch (e) { return null; } }
  opts.forEach(function (b) {
    b.addEventListener('click', function () { applyTheme(b.getAttribute('data-theme')); });
  });
  applyTheme(currentTheme() || 'vault');

  /* ---------- 유틸 ---------- */
  function fmt(n) { return Number(n).toLocaleString('ko-KR'); }

  function showFlash(type, msg) {
    var host = document.querySelector('.page-content');
    if (!host) return;
    var el = document.createElement('div');
    el.className = 'flash flash-' + (type === 'ok' ? 'ok' : 'err');
    el.textContent = msg;
    host.insertBefore(el, host.firstChild);
    setTimeout(function () {
      el.style.opacity = '0';
      el.style.transition = 'opacity .4s';
    }, 3500);
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 4000);
  }

  /* ---------- 실시간 쿨다운 (.cd-box) ----------
     초기 렌더(서버가 data-cd=남은초) → 매초 .cd-sec 감소,
     0 도달 시 data-action/label로 활성 폼 주입 (새로고침 없이 활성화). */
  function enableBox(box) {
    clearTimeout(box._timer);
    box.innerHTML =
      '<form method="post" action="' + box.dataset.action + '" class="ajax-form">' +
      '<button class="btn ' + (box.dataset.color || '') + '">' + box.dataset.label + '</button></form>';
  }
  function tickCountdown(box, sec) {
    var secEl = box.querySelector('.cd-sec');
    if (secEl) secEl.textContent = sec;
    if (sec <= 0) { enableBox(box); return; }
    box._timer = setTimeout(function () { tickCountdown(box, sec - 1); }, 1000);
  }
  function renderCountdown(box, secs) {
    clearTimeout(box._timer);
    box.innerHTML = '<button class="btn btn-sm" disabled>쿨다운 <span class="cd-sec">' +
      Math.ceil(secs) + '</span>초</button>';
    tickCountdown(box, Math.ceil(secs));
  }
  document.querySelectorAll('.cd-box').forEach(function (box) {
    var secs = parseInt(box.dataset.cd || '0', 10);
    if (secs > 0) tickCountdown(box, secs);
  });

  /* ---------- AJAX 액션 (.ajax-form) ---------- */
  function updateCash(cash) {
    var first = document.querySelector('.js-cash');
    var oldCash = first ? (parseInt(first.dataset.raw, 10) || 0) : 0;
    var totalEl = document.querySelector('.js-total');
    var oldTotal = totalEl ? (parseInt(totalEl.dataset.raw, 10) || 0) : 0;
    document.querySelectorAll('.js-cash').forEach(function (el) {
      el.dataset.raw = cash;
      el.textContent = fmt(cash) + '원';
    });
    if (totalEl) {
      var nt = oldTotal + (cash - oldCash);
      totalEl.dataset.raw = nt;
      totalEl.textContent = fmt(nt) + '원';
    }
  }
  function updateLevel(level) {
    document.querySelectorAll('.js-level').forEach(function (el) {
      el.dataset.raw = level;
      el.textContent = 'Lv.' + level;
    });
  }

  function ajaxSubmit(form) {
    var btn = form.querySelector('button');
    if (btn) { btn.disabled = true; }
    var body = new FormData(form);
    fetch(form.action, {
      method: 'POST',
      body: body,
      headers: { 'Accept': 'application/json' },
      credentials: 'same-origin'
    })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (data) {
        if (btn) btn.disabled = false;
        if (data.cash != null) updateCash(data.cash);
        if (data.leveled_up && data.level != null) updateLevel(data.level);
        var cdKeys = ['beg_left', 'alba_left', 'work_left'];
        for (var i = 0; i < cdKeys.length; i++) {
          if (data[cdKeys[i]] != null) {
            var box = document.querySelector('.cd-box[data-action="' + form.getAttribute('action') + '"]');
            if (box) renderCountdown(box, data[cdKeys[i]]);
            break;
          }
        }
        showFlash(data.ok ? 'ok' : 'err', data.msg || '완료');
      })
      .catch(function () {
        if (btn) btn.disabled = false;
        showFlash('err', '네트워크 오류 — 다시 시도해주세요.');
      });
  }
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.classList.contains('ajax-form')) return;
    e.preventDefault();
    ajaxSubmit(form);
  });

  /* ---------- 리빌 효과 ---------- */
  var els = Array.prototype.slice.call(
    document.querySelectorAll('.card, .stat, .hero, .auth-wrap, table, .feature-card, .net-worth')
  );
  function revealAll() { els.forEach(function (el) { el.classList.add('revealed'); }); }
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('revealed');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.05, rootMargin: '0px 0px -4% 0px' });
    els.forEach(function (el) { io.observe(el); });
  } else {
    revealAll();
  }
})();