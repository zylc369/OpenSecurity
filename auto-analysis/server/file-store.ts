// server/file-store.ts — private_data 文件读写（加锁 + 原子写入）
import fs from "node:fs"
import path from "node:path"
import os from "node:os"
import lockfile from "proper-lockfile"
import { fileURLToPath } from "node:url"

const __dirname = import.meta.dirname ?? path.dirname(fileURLToPath(import.meta.url))
const PRIVATE_DATA_DIR = path.resolve(__dirname, "../private_data")

/** 确保 private_data 目录存在 */
function ensureDir() {
  if (!fs.existsSync(PRIVATE_DATA_DIR)) {
    fs.mkdirSync(PRIVATE_DATA_DIR, { recursive: true })
  }
}

/** 获取文件的绝对路径 */
function filePath(filename: string): string {
  ensureDir()
  return path.join(PRIVATE_DATA_DIR, filename)
}

/**
 * 加锁读取 JSON 文件
 *
 * 读取前获取文件锁 → 读取 → 释放锁。
 * 文件不存在时返回 null。
 */
export async function readJson<T>(filename: string): Promise<T | null> {
  const fpath = filePath(filename)

  // proper-lockfile 要求文件存在才能加锁；不存在则返回 null
  if (!fs.existsSync(fpath)) return null

  const release = await lockfile.lock(fpath, { retries: 3, stale: 10000 })
  try {
    const content = fs.readFileSync(fpath, "utf8")
    return JSON.parse(content) as T
  } finally {
    await release()
  }
}

/**
 * 加锁原子写入 JSON 文件
 *
 * 写入前获取文件锁 → 写入临时文件 → rename 原子替换 → 释放锁。
 * rename 是原子的（同一文件系统），保证不会出现半写状态。
 */
export async function writeJson<T>(filename: string, data: T): Promise<void> {
  const fpath = filePath(filename)
  ensureDir()

  // 确保目标文件存在（proper-lockfile 需要文件存在）
  if (!fs.existsSync(fpath)) {
    fs.writeFileSync(fpath, "{}", "utf8")
  }

  const release = await lockfile.lock(fpath, { retries: 3, stale: 10000 })
  try {
    const tmpPath = fpath + ".tmp"
    fs.writeFileSync(tmpPath, JSON.stringify(data, null, 2), "utf8")
    fs.renameSync(tmpPath, fpath)
  } finally {
    await release()
  }
}
