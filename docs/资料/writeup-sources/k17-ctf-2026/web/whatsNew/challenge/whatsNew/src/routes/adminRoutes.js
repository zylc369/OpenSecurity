const express = require("express");
const { page, view } = require("../view");
const store = require("../store");
const { instanceEnv } = require("../instanceEnv");

const router = express.Router();

function adminBotOnly(req, res, next) {
    const expectedToken = instanceEnv("ADMIN_BOT_TOKEN");
    const providedToken = req.cookies?.admin_bot_token;

    if (!expectedToken || providedToken !== expectedToken) {
        return res.status(403).type("text/plain").send("forbidden");
    }

    return next();
}

router.use("/admin", adminBotOnly);

router.get("/admin", (req, res) => {
    res.send(page("Admin", view("admin")));
});

router.get("/admin/preview", (req, res) => {
    const posts = store
        .latestPosts()
        .map(({ category, post }) => {
            if (!post) {
                return `
          <article class="post-card">
            <h2>${category.label}</h2>
            <p>No posts yet.</p>
          </article>
        `;
            }

            return category.renderPost(post);
        })
        .join("");

    res.send(page("Latest posts", view("admin-preview", { posts })));
});

module.exports = router;
