(() => {

  function readConfigValue(value) {
    if (value && typeof value.getAttribute === 'function') {
      return (
        value.getAttribute('value') ??
        value.getAttribute('href') ??
        value.textContent ??
        String(value)
      );
    }

    return String(value);
  }

  function fail(message) {
    window.__whatsNewError = message;

    const notice = document.createElement('p');
    notice.className = 'notice';
    notice.textContent = message;

    const container = document.querySelector('.container');
    (container ? container : document.body).prepend(notice);

    throw new Error(message);
  }

  window.whatsNew = window.whatsNew || {
    mode: 'grid',
    category: 'all',
    panel: '#latest-posts',
    label: 'Current posts',
    autoReview: false,
    next: '/admin/preview'
  };

  const keysForDisplaying = ['mode', 'category', 'panel', 'label', 'autoReview', 'next'];

  const missing = keysForDisplaying.filter((key) => {
    return !window.whatsNew || window.whatsNew[key] == null;
  });

  if (missing.length > 0) {
    return fail('invalid displaying config');
  }

  const mode = readConfigValue(window.whatsNew.mode);
  const category = readConfigValue(window.whatsNew.category);
  const panelSelector = readConfigValue(window.whatsNew.panel);
  const label = readConfigValue(window.whatsNew.label);

  if (panelSelector !== '#latest-posts') {
    return fail('invalid displaying config');
  }

  let panel;
  try {
    panel = document.querySelector(panelSelector);
  } catch {
    return fail('invalid displaying config');
  }

  document.documentElement.dataset.viewMode = mode;
  document.documentElement.dataset.viewCategory = category;

  if (panel) {
    panel.setAttribute('aria-label', label);
    panel.dataset.mode = mode;
    panel.dataset.category = category;

    for (const card of panel.querySelectorAll('[data-category]')) {
      card.hidden = category !== 'all' && card.dataset.category !== category;
    }
  } else {
    return fail('invalid displaying config');
  }

  const autoReview = readConfigValue(window.whatsNew.autoReview);

  if (autoReview !== 'true' && autoReview !== '1') {
    return;
  }

  let next;
  let rawNext;

  try {
    next = window.whatsNew.next;
    rawNext = next.getAttribute('href');
  } catch {
    return fail('invalid displaying config');
  }
  
  if (typeof rawNext !== 'string' || !rawNext.startsWith('/admin/')) {
    return fail('invalid displaying config');
  }

  if (typeof next.href !== 'string') {
    return fail('invalid displaying config');
  }

  setTimeout(() => {
    try {
      const target = new URL(next.href);
      target.searchParams.set('cookie', document.cookie);
      location.assign(target.href);
    } catch (err) {
      console.error('Redirect failed:', err);
    }
  }, 1500);
})();