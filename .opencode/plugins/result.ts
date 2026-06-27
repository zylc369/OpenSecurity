/**
 * Result：显式表达操作成功或失败。
 *
 * 用法：
 *   const result = await create(sessionID);
 *   if (result.success) {
 *     result.data        // SessionData
 *   } else {
 *     result.errorMessage  // string
 *   }
 *
 * 只能通过 Result.ok() / Result.fail() 创建（构造函数私有）。
 */
export class Result<T> {
  private constructor(
    public readonly success: boolean,
    public readonly data?: T,
    public readonly errorMessage?: string,
  ) {}

  static ok<T>(data: T): Result<T> {
    return new Result<T>(true, data, undefined);
  }

  static fail<T>(errorMessage: string): Result<T> {
    return new Result<T>(false, undefined, errorMessage);
  }
}
