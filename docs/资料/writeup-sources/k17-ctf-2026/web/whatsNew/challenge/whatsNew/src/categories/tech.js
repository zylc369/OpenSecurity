const { escapeHtml, raw, formatDate } = require('../html');

function clean(value) {
  return String(value ?? '');
}

function buildPost(input) {
  return {
    title: clean(input.title),
    author: clean(input.author),
    description: clean(input.description).slice(0, 200),
    reference: clean(input.reference)
  };
}

function renderPost(post) {
  return `
    <article class="post-card" data-category="tech" data-post-id="${raw(post.id)}">
      <header>
        <p class="category-label">Tech</p>
        <h2>${escapeHtml(post.title)}</h2>
        <p class="meta">${escapeHtml(post.author || 'anonymous')} · ${formatDate(post.createdAt)}</p>
      </header>
      <p class="reference-line">${escapeHtml(post.reference)}</p>
      <div class="post-description">${raw(post.description)}</div>
    </article>
  `;
}

module.exports = {
  slug: 'tech',
  label: 'Tech',
  buildPost,
  renderPost,
  fields: [
    { name: 'title', label: 'Title', type: 'text', placeholder: 'Post title' },
    { name: 'author', label: 'Author', type: 'text', placeholder: 'editor' },
    { name: 'description', label: 'Description', type: 'textarea', placeholder: 'Short write-up', maxLength: 200 },
    { name: 'reference', label: 'Reference', type: 'text', placeholder: 'Reference' }
  ]
};
