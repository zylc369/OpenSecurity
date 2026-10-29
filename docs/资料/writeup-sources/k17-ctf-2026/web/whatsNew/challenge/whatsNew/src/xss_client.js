// Talks to the shared XSS bot. On the instantiator the bot URL, token, and this instance's
// id are injected into /run/instantiator.env after the snapshot restore, so they are read
// at call time (see instanceEnv), not at module load.

const { instanceEnv } = require("./instanceEnv");

class XSSBotError extends Error {
    constructor(message, options = {}) {
        super(message, options);
        this.name = "XSSBotError";
    }
}

async function requestVisit(path, { timeoutMs = 5000 } = {}) {
    const botUrl = (instanceEnv("XSS_BOT_URL") || "").replace(/\/+$/, "");
    const botToken = instanceEnv("XSS_BOT_TOKEN");
    const instanceId = instanceEnv("INSTANCE_ID");

    if (!botUrl) {
        throw new XSSBotError("XSS_BOT_URL is not configured");
    }
    if (!botToken) {
        throw new XSSBotError("XSS_BOT_TOKEN is not configured");
    }
    if (!instanceId) {
        throw new XSSBotError("INSTANCE_ID is not configured");
    }
    if (typeof path !== "string") {
        throw new TypeError("path must be a string");
    }
    if (!path.startsWith("/") || path.startsWith("//")) {
        throw new RangeError("path must begin with exactly one forward slash");
    }
    if (path.length > 2048) {
        throw new RangeError("path must not exceed 2048 characters");
    }

    let response;
    try {
        response = await fetch(`${botUrl}/visit`, {
            method: "POST",
            headers: {
                Authorization: `Bearer ${botToken}`,
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ path, instanceId }),
            signal: AbortSignal.timeout(timeoutMs),
        });
    } catch (error) {
        const message =
            error?.name === "TimeoutError"
                ? `Timed out contacting XSS bot at ${botUrl}`
                : `Could not contact XSS bot at ${botUrl}`;
        throw new XSSBotError(message, { cause: error });
    }

    if (response.status !== 202) {
        const responseText = await response.text();
        throw new XSSBotError(
            `XSS bot returned HTTP ${response.status}: ${responseText}`,
        );
    }
}

module.exports = {
    requestVisit,
    XSSBotError,
};
