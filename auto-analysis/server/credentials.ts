// server/credentials.ts — 凭据加密/解密管理
import crypto from "node:crypto"
import os from "node:os"
import { readJson, writeJson } from "./file-store.js"

const CREDENTIALS_FILE = "credentials.json"

/** 凭据条目 */
export interface CredentialEntry {
  username: string
  password: string
}

/** 存储格式：{ siteUrl: { iv, tag, encrypted } } */
interface EncryptedEntry {
  iv: string       // Base64 编码的初始化向量
  tag: string      // Base64 编码的 GCM 认证标签
  encrypted: string // Base64 编码的密文
}

type CredentialsStore = Record<string, EncryptedEntry>

/**
 * 机器指纹 → PBKDF2 → 32 字节密钥
 *
 * 指纹由 hostname + username + platform + 首个非内部 MAC 地址组成。
 * 密钥在进程生命周期内缓存。
 */
let cachedKey: Buffer | null = null
function getDerivationKey(): Buffer {
  if (cachedKey) return cachedKey

  const hostname = os.hostname()
  const username = os.userInfo().username
  const platform = os.platform()

  // 获取首个非内部 MAC 地址
  const nets = os.networkInterfaces()
  let mac = "no-mac"
  for (const entries of Object.values(nets)) {
    for (const entry of entries ?? []) {
      if (entry.mac && entry.mac !== "00:00:00:00:00:00" && !entry.internal) {
        mac = entry.mac
        break
      }
    }
    if (mac !== "no-mac") break
  }

  const fingerprint = `${hostname}:${username}:${platform}:${mac}`
  cachedKey = crypto.pbkdf2Sync(fingerprint, "auto-analysis-salt", 100000, 32, "sha256")
  return cachedKey
}

/** AES-256-GCM 加密 */
function encrypt(plaintext: string): EncryptedEntry {
  const key = getDerivationKey()
  const iv = crypto.randomBytes(12) // GCM 推荐 12 字节 IV
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv)
  const encrypted = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()])
  const tag = cipher.getAuthTag()

  return {
    iv: iv.toString("base64"),
    tag: tag.toString("base64"),
    encrypted: encrypted.toString("base64"),
  }
}

/** AES-256-GCM 解密 */
function decrypt(entry: EncryptedEntry): string {
  const key = getDerivationKey()
  const iv = Buffer.from(entry.iv, "base64")
  const tag = Buffer.from(entry.tag, "base64")
  const encrypted = Buffer.from(entry.encrypted, "base64")

  const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv)
  decipher.setAuthTag(tag)
  return Buffer.concat([decipher.update(encrypted), decipher.final()]).toString("utf8")
}

/** 保存网站凭据（加密后存储） */
export async function saveCredentials(siteUrl: string, username: string, password: string): Promise<void> {
  const store = (await readJson<CredentialsStore>(CREDENTIALS_FILE)) ?? {}
  store[siteUrl] = encrypt(JSON.stringify({ username, password }))
  await writeJson(CREDENTIALS_FILE, store)
}

/** 读取网站凭据（解密后返回） */
export async function getCredentials(siteUrl: string): Promise<CredentialEntry | null> {
  const store = await readJson<CredentialsStore>(CREDENTIALS_FILE)
  if (!store || !store[siteUrl]) return null

  const decrypted = decrypt(store[siteUrl]!)
  return JSON.parse(decrypted) as CredentialEntry
}
