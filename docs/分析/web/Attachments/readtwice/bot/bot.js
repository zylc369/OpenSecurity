const puppeteer = require("puppeteer");

const APP_URL = process.env.APP_URL || "http://127.0.0.1:3000";
const BOT_TOKEN = process.env.BOT_TOKEN || "dev-token";
const CHROMIUM_PATH = process.env.PUPPETEER_EXECUTABLE_PATH || "/usr/bin/chromium";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function locationKey(value) {
  const url = new URL(value);
  url.hash = "";
  return url.href;
}

function isReportDocument(value, report) {
  const url = new URL(value);
  const app = new URL(APP_URL);

  return url.origin === app.origin
    && url.pathname === "/reports/check"
    && url.searchParams.get("rid") === report.id;
}

function watchDocument(page, report, entryUrl) {
  const entry = locationKey(entryUrl);
  let entered = false;
  let diverged = false;

  page.on("request", (request) => {
    if (!request.isNavigationRequest() || request.frame() !== page.mainFrame()) {
      return;
    }

    const next = request.url();

    if (!entered) {
      entered = locationKey(next) === entry;
      diverged = !entered;
      return;
    }

    if (isReportDocument(next, report)) {
      report.finalized = report.approved && !diverged;
      return;
    }

    if (locationKey(next) !== entry) {
      diverged = true;
      report.finalized = false;
    }
  });
}

async function inspectDocument(source) {
  let browser;

  try {
    browser = await puppeteer.launch({
      executablePath: CHROMIUM_PATH,
      headless: "new",
      args: [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        '--js-flags="--jitless"',
        "--disable-gpu",
      ],
    });

    const page = await browser.newPage();
    await page.setJavaScriptEnabled(false);
    await page.setOfflineMode(true);
    await page.setContent(source, {
      waitUntil: "domcontentloaded",
      timeout: 5000,
    });

    return await page.evaluate(() => {
      const declaration = document.head.firstElementChild;
      const surface = document.body.firstElementChild;
      const attributeProfile = [
        [document.documentElement, []],
        [document.head, []],
        [document.body, []],
        [declaration, ["http-equiv", "content"]],
        [surface, []],
      ].every(([element, allowed]) => element
        && element.getAttributeNames().every((name) => allowed.includes(name)));

      return document.doctype?.name === "html"
        && document.head.childElementCount === 1
        && declaration?.localName === "meta"
        && declaration.httpEquiv.toLowerCase() === "content-security-policy"
        && declaration.content === "default-src 'none'"
        && document.body.childElementCount === 1
        && surface?.localName === "div"
        && surface.childElementCount === 0
        && document.body.textContent.trim() === ""
        && attributeProfile;
    });
  } catch {
    return false;
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

async function review(report) {
  let browser;
  let context;

  try {
    browser = await puppeteer.launch({
      executablePath: CHROMIUM_PATH,
      headless: "new",
      args: [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        '--js-flags="--jitless"',
        "--disable-gpu",
      ],
    });

    context = await browser.createBrowserContext();

    const sessionPage = await context.newPage();
    await sessionPage.setExtraHTTPHeaders({ "X-Bot-Token": BOT_TOKEN });
    const sessionResponse = await sessionPage.goto(`${APP_URL}/reports/session`, {
      waitUntil: "domcontentloaded",
      timeout: 7000,
    });

    await sessionPage.close();
    if (!sessionResponse || !sessionResponse.ok()) {
      throw new Error(`reviewer session returned ${sessionResponse ? sessionResponse.status() : "no response"}`);
    }

    const setupPage = await context.newPage();

    await setupPage.goto(`${APP_URL}/reports/check?rid=${encodeURIComponent(report.id)}`, {
      waitUntil: "domcontentloaded",
      timeout: 7000,
    });

    await setupPage.goto(`${APP_URL}/api/flag`, {
      waitUntil: "domcontentloaded",
      timeout: 7000,
    });

    await setupPage.close();

    const armResponse = await fetch(`${APP_URL}/reports/arm/${encodeURIComponent(report.id)}`, {
      method: "POST",
      headers: { "X-Bot-Token": BOT_TOKEN },
    });

    if (!armResponse.ok) {
      throw new Error(`report arm returned ${armResponse.status}`);
    }

    const page = await context.newPage();
    const url = new URL(report.url);
    url.searchParams.set("rid", report.id);
    watchDocument(page, report, url.href);

    await page.goto(url.href, {
      waitUntil: "domcontentloaded",
      timeout: 7000,
    });

    await sleep(10000);
    await page.close();
  } finally {
    if (context) {
      await context.close();
    }
    if (browser) {
      await browser.close();
    }
  }
}

module.exports = { inspectDocument, review };
