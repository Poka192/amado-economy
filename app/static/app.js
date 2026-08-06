/* 아마도 경제 — 리빌 효과.
   'html.js' 클래스는 base.html의 인라인 스크립트가 미리 넣어 두어
   JS가 실패해도 콘텐츠는 보이게 된다. */
(function () {
  'use strict';

  document.documentElement.classList.add('js');

  // 스크롤 진입 시 페이드업 리빌
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