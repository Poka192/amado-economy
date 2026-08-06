/* 아마도 경제 — 테마 전환 + 리빌 효과.
   'html.js' 클래스와 테마 복원은 base.html 인라인 스크립트가 paint 전에 처리. */
(function () {
  'use strict';

  var root = document.documentElement;
  root.classList.add('js');

  // ---------- 테마 전환 ----------
  var THEMES = ['vault', 'midnight', 'emerald', 'paper'];
  var opts = Array.prototype.slice.call(document.querySelectorAll('.theme-opt'));

  function applyTheme(name) {
    root.setAttribute('data-theme', name);
    try { localStorage.setItem('theme', name); } catch (e) {}
    opts.forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-theme') === name);
    });
  }

  function currentTheme() {
    try { return localStorage.getItem('theme'); } catch (e) { return null; }
  }

  opts.forEach(function (b) {
    b.addEventListener('click', function () { applyTheme(b.getAttribute('data-theme')); });
  });

  // 로드 시 스위처 활성 상태 동기화 (인라인 스크립트가 이미 적용했지만, 액티브 표시용)
  applyTheme(currentTheme() || 'vault');

  // ---------- 리빌 효과 ----------
  var els = Array.prototype.slice.call(
    document.querySelectorAll(
      '.card, .stat, .hero, .auth-wrap, table, .feature-card, .net-worth'
    )
  );

  function revealAll() {
    els.forEach(function (el) { el.classList.add('revealed'); });
  }

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