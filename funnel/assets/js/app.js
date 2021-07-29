/* global jstz, Pace */

import { Utils, ScrollActiveMenu, LazyloadImg } from './util';

$(() => {
  window.Hasgeek.Config.availableLanguages = {
    en: 'en_IN',
    hi: 'hi_IN',
  };
  window.Hasgeek.Config.mobileBreakpoint = 768; // this breakpoint switches to desktop UI
  window.Hasgeek.Config.ajaxTimeout = 30000;
  window.Hasgeek.Config.retryInterval = 10000;
  window.Hasgeek.Config.closeModalTimeout = 10000;
  window.Hasgeek.Config.refreshInterval = 60000;
  window.Hasgeek.Config.notificationRefreshInterval = 300000;
  window.Hasgeek.Config.readReceiptTimeout = 5000;
  window.Hasgeek.Config.saveEditorContentTimeout = 300;
  window.Hasgeek.Config.userAvatarImgSize = {
    big: '160',
    medium: '80',
    small: '48',
  };
  Utils.loadLangTranslations();
  window.Hasgeek.Config.errorMsg = {
    serverError: window.gettext(
      'An internal server error occurred. Our support team has been notified and will investigate'
    ),
    networkError: window.gettext(
      'Unable to connect. Check connection and tap to reload'
    ),
  };

  Utils.collapse();
  Utils.smoothScroll();
  Utils.navSearchForm();
  Utils.headerMenuDropdown(
    '.js-menu-btn',
    '.js-account-menu-wrapper',
    '.js-account-menu',
    window.Hasgeek.Config.accountMenu
  );
  Utils.scrollTabs();
  Utils.truncate();
  Utils.showTimeOnCalendar();
  Utils.popupBackHandler();
  Utils.handleModalForm();
  if ($('.header__nav-links--updates').length) {
    Utils.updateNotificationStatus();
    window.setInterval(
      Utils.updateNotificationStatus,
      window.Hasgeek.Config.notificationRefreshInterval
    );
  }
  Utils.addWebShare();
  Utils.activateToggleSwitch();
  if (window.Hasgeek.Config.commentSidebarElem) {
    Utils.headerMenuDropdown(
      '.js-comments-btn',
      '.js-comments-wrapper',
      '.js-comment-sidebar',
      window.Hasgeek.Config.unreadCommentUrl
    );
  }
  Utils.addVegaSupport();

  const intersectionObserverComponents =
    function intersectionObserverComponents() {
      if (document.querySelector('#page-navbar')) {
        ScrollActiveMenu.init(
          'page-navbar',
          'sub-navbar__item',
          'sub-navbar__item--active'
        );
      }
      LazyloadImg.init('js-lazyload-img');
    };

  if (
    document.querySelector('#page-navbar') ||
    document.querySelector('.js-lazyload-img') ||
    document.querySelector('.js-lazyload-results')
  ) {
    if (
      !(
        'IntersectionObserver' in global &&
        'IntersectionObserverEntry' in global &&
        'intersectionRatio' in IntersectionObserverEntry.prototype
      )
    ) {
      const polyfill = document.createElement('script');
      polyfill.setAttribute('type', 'text/javascript');
      polyfill.setAttribute(
        'src',
        'https://cdn.polyfill.io/v2/polyfill.min.js?features=IntersectionObserver'
      );
      polyfill.onload = function loadintersectionObserverComponents() {
        intersectionObserverComponents();
      };
      document.head.appendChild(polyfill);
    } else {
      intersectionObserverComponents();
    }
  }

  if (!('URLSearchParams' in window)) {
    const polyfill = document.createElement('script');
    polyfill.setAttribute('type', 'text/javascript');
    polyfill.setAttribute(
      'src',
      'https://cdnjs.cloudflare.com/ajax/libs/url-search-params/1.1.0/url-search-params.js'
    );
    document.head.appendChild(polyfill);
  }

  // Send click events to Google analytics
  $('.mui-btn, a').click(function gaHandler() {
    const action =
      $(this).attr('data-ga') || $(this).attr('title') || $(this).html();
    const target = $(this).attr('data-target') || $(this).attr('href') || '';
    Utils.sendToGA('click', action, target);
  });
  $('.search-form__submit').click(function gaHandler() {
    const target = $('.js-search-field').val();
    Utils.sendToGA('search', target, target);
  });

  // Detect timezone for login
  if ($.cookie('timezone') === null) {
    $.cookie('timezone', jstz.determine().name(), { path: '/' });
  }
});

if (
  navigator.userAgent.match(/(iPhone|Android)/) &&
  !(
    window.navigator.standalone === true ||
    window.matchMedia('(display-mode: standalone)').matches
  )
) {
  $('.pace').addClass('pace-hide');
  window.onbeforeunload = function stopPace() {
    Pace.stop();
  };
}
