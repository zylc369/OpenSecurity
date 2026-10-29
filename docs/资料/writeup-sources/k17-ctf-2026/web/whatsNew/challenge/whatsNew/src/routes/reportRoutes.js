const express = require("express");
const { page, view } = require("../view");
const { visitLatestPosts, XSSBotError } = require("../bot");

const router = express.Router();

function message(text, href) {
    return `
    <section class="section-block narrow">
      <p>${text}</p>
      <a class="button" href="${href}">Back</a>
    </section>
  `;
}

router.get("/report", (req, res) => {
    res.send(page("Report", view("report")));
});

router.post("/report", async (req, res) => {
    try {
        await visitLatestPosts();

        res.status(202).send(
            page("Report sent", message("Report queued for review.", "/")),
        );
    } catch (error) {
        console.error("[report] XSS bot request failed:", error);

        const text =
            error instanceof XSSBotError
                ? "The admin bot is currently unavailable."
                : "Could not submit the report.";

        res.status(503).send(page("Error", message(text, "/report")));
    }
});

module.exports = router;
