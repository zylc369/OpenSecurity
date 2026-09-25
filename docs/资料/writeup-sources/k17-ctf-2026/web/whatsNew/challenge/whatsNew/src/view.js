const fs = require('fs');
const path = require('path');

const viewsDir = path.join(__dirname, '..', 'views');

function readView(name) {
  return fs.readFileSync(path.join(viewsDir, `${name}.html`), 'utf8');
}

function fill(template, values) {
  return template.replace(/{{\s*([a-zA-Z0-9_]+)\s*}}/g, (_, key) => {
    return Object.prototype.hasOwnProperty.call(values, key) ? String(values[key]) : '';
  });
}

function page(title, body, extra = {}) {
  return fill(readView('layout'), {
    title,
    pageTitle: extra.pageTitle || title,
    body,
    nav: extra.nav || ''
  });
}

function view(name, values = {}) {
  return fill(readView(name), values);
}

module.exports = {
  page,
  view
};
