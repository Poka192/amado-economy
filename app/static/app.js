/* 아마도 경제 — 리빌 + 네비 향상.
   'html.js' 클래스는 base.html의 인라인 스크립트가 미리 넣어 두어
   JS가 실패해도 콘텐츠는 보이게 된다. 여기선 관찰/스크롤만 담당. */
(function () {
  'use strict';

  var root = document.documentElement;
  root.classList.add('js');

  // 네비 스크롤 시 그림자/테두리 강화
  var nav = document.querySelector('.navbar');
  if (nav) {
    var onScroll = function () {
      nav.classList.toggle('scrolled', window.scrollY > 6);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  // 스크롤 진입 시 페이드업 리빌
  var els = Array.prototype.slice.call(
    document.querySelectorAll('.card, .stat, .hero, .auth-wrap, table')
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