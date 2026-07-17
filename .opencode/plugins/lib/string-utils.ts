export default class StringUtils {
  /**
   * 安全地将值转为字符串：对象转为 JSON 字符串，其他类型安全转为普通字符串
   * @param {any} val - 待转换的值
   * @returns {string | null | undefined} - 如果传入 null/undefined 则原样返回，否则返回字符串
   */
  static toStringSafe(val: any): string | null | undefined {
    // 1. 处理 null 和 undefined，返回默认值，避免转为 "null" / "undefined"
    if (val === null || val === undefined) return val;

    // 2. 如果已经是字符串，直接返回
    if (typeof val === "string") return val;

    try {
      // 3. 如果是对象或数组，转为 JSON 字符串
      if (typeof val === "object") return JSON.stringify(val);
    } catch (e) {
      console.error("[StringUtils.toStringSafe] JSON序列化失败:", e);
      return String(val); // 序列化失败时降级为普通字符串，例如 "[object Object]"
    }

    // 4. 其他基本类型（number, boolean 等）安全转为字符串
    return String(val);
  }
}
