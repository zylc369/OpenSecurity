const { requestVisit, XSSBotError } = require("./xss_client");

async function visitLatestPosts() {
    await requestVisit("/admin/preview");
}

module.exports = {
    visitLatestPosts,
    XSSBotError,
};
