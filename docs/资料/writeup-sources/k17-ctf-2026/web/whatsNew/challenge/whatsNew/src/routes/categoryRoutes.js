const express = require('express');
const { page, view } = require('../view');
const { escapeHtml } = require('../html');
const { listCategories, getCategory } = require('../categories');
const store = require('../store');
const { decodeHtml, isSuspicious } = require('../filter');

const router = express.Router();

function renderCategoryCard(category) {
  const post = store.latestPost(category.slug);
  const title = post ? post.title : 'No posts yet';

  return `
    <a class="card-link" href="/category/${category.slug}">
      <h2>${category.label}</h2>
      <p>${escapeHtml(title)}</p>
    </a>
  `;
}

function renderField(field) {
  const label = field.label;
  const name = field.name;
  const placeholder = field.placeholder || '';
  const maxLength = field.maxLength ? ` maxlength="${field.maxLength}"` : '';

  if (field.type === 'textarea') {
    return `
      <label>
        <span>${label}</span>
        <textarea name="${name}" rows="5" placeholder="${placeholder}"${maxLength}></textarea>
      </label>
    `;
  }

  return `
    <label>
      <span>${label}</span>
      <input name="${name}" type="text" placeholder="${placeholder}"${maxLength}>
    </label>
  `;
}

router.get('/', (req, res) => {
  const categoryCards = listCategories().map(renderCategoryCard).join('');
  res.send(page('whatsNew', view('index', { categoryCards }), { pageTitle: 'Posts' }));
});

router.get('/category/:slug', (req, res) => {
  const category = getCategory(req.params.slug);
  if (!category) return res.status(404).send(page('Not found', '<p>Category not found.</p>'));

  const posts = store.listPosts(category.slug).map((post) => category.renderPost(post)).join('') || '<p>No posts yet.</p>';
  const body = view('category', {
    slug: category.slug,
    posts
  });

  res.send(page(`${category.label} posts`, body));
});

router.get('/category/:slug/new', (req, res) => {
  const category = getCategory(req.params.slug);
  if (!category) return res.status(404).send(page('Not found', '<p>Category not found.</p>'));

  const fields = category.fields.map(renderField).join('');
  const body = view('new-post', {
    slug: category.slug,
    fields
  });

  res.send(page(`New ${category.label} post`, body));
});

router.post('/category/:slug/new', (req, res) => {
  const category = getCategory(req.params.slug);
  if (!category) return res.status(404).send(page('Not found', '<p>Category not found.</p>'));

  const decodedDescription = decodeHtml(req.body.description);

  if (isSuspicious(decodedDescription)) {
    return res.status(400).send(page('Suspicious', '<section class="section-block narrow"><p>suspicious!</p><a class="button" href="/">Back</a></section>'));
  }

  req.body.description = decodedDescription;
  store.addPost(category.slug, req.body);
  res.redirect(`/category/${encodeURIComponent(category.slug)}`);
});

module.exports = router;
