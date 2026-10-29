const tech = require('./tech');
const travel = require('./travel');
const food = require('./food');
const lifestyle = require('./lifestyle');

const categories = [tech, travel, food, lifestyle];
const bySlug = new Map(categories.map((category) => [category.slug, category]));

function listCategories() {
  return categories;
}

function getCategory(slug) {
  return bySlug.get(slug);
}

module.exports = {
  listCategories,
  getCategory
};
