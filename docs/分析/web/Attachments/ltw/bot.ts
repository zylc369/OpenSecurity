import { sleep } from 'bun'
import { Challenge, type ChallengeContext } from '../src/types'

const APP_HOST = 'ltw.chals.sekai.team'
const APP_URL = `https://${APP_HOST}`

export const challenge = new Challenge({
  timeoutMilliseconds: 30_000,

  inputs: {
    id: {
      pattern: '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$',
    },
  },

  handler: async (ctx: ChallengeContext): Promise<void> => {
    const url = `${APP_URL}/notes/${ctx.input.id!}`
    ctx.output.info('challenge', `visiting note`, { url })

    await ctx.browserContext.setCookie({
      name: 'FLAG',
      value: ctx.job.flag,
      domain: APP_HOST,
      path: '/',
    })

    const page = await ctx.browserContext.newPage()

    try {
      await page.goto(url)
    } catch (e) {
      ctx.output.fatal('challenge', `failed to visit provided URL: ${e}`, { url })
      return
    }

    await sleep(5_000)
    await page.close()
  },

  hooksConfig: {
    showConsoleLogs: true,
    showBrowserErrors: true,
    showNavigation: true,
    showDialogs: true,
    autoDismissDialogs: true,
    limitTabsNumber: -1,
    limitTabsNumberShowError: true,
  },

  browser: 'chrome',

  restrictDomains: {
    host: {
      allowRegex: [{ pattern: '^ltw\.chals\.sekai\.team$' }],
      disallowRegex: [{ pattern: '.*' }],
    },
  },
})