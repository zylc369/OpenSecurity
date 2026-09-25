const crypto = require('crypto');
const { listCategories, getCategory } = require('./categories');

const postsByCategory = new Map();

for (const category of listCategories()) {
  postsByCategory.set(category.slug, []);
}

function now() {
  return new Date().toISOString();
}

function addPost(categorySlug, input) {
  const category = getCategory(categorySlug);
  if (!category) return null;

  const post = {
    id: crypto.randomUUID(),
    category: categorySlug,
    createdAt: now(),
    ...category.buildPost(input)
  };

  postsByCategory.get(categorySlug).unshift(post);
  return post;
}

function listPosts(categorySlug) {
  return postsByCategory.get(categorySlug) || [];
}

function latestPost(categorySlug) {
  return listPosts(categorySlug)[0] || null;
}

function latestPosts() {
  return listCategories().map((category) => ({
    category,
    post: latestPost(category.slug)
  }));
}

module.exports = {
  addPost,
  listPosts,
  latestPost,
  latestPosts
};
