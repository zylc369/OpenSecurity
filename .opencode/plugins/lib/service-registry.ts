/**
 * 服务启动状态注册表。
 *
 * 统一管理 embed_server、env_check 等异步启动的服务的状态。
 * chat.message 通过 waitFor() 等待所有依赖服务就绪后再放行。
 *
 * 支持多个 waitFor 并发等待同一个服务（如多个 session 同时触发 chat.message）。
 */

export interface ServiceStatus {
    name: string;
    status: "pending" | "success" | "failed";
    error?: string;
    metadata?: Record<string, any>;
    startedAt: number;
    completedAt?: number;
}

export class ServiceRegistry {
    private services = new Map<string, ServiceStatus>();
    // 每个服务名对应一个 resolver 数组——支持多个 waitFor 并发等待
    private resolvers = new Map<string, Array<(svc: ServiceStatus) => void>>();

    /** 注册一个待启动的服务。重复注册同名服务会被忽略（幂等）。 */
    register(name: string): void {
        if (this.services.has(name)) return;
        this.services.set(name, {
            name,
            status: "pending",
            startedAt: Date.now(),
        });
    }

    /** 标记服务为成功或失败。唤醒所有等待此服务的 waitFor。 */
    resolve(
        name: string,
        status: "success" | "failed",
        error?: string,
        metadata?: Record<string, any>,
    ): void {
        const svc = this.services.get(name);
        if (svc) {
            svc.status = status;
            svc.error = error;
            svc.metadata = metadata;
            svc.completedAt = Date.now();
        }
        // 唤醒所有等待此服务的 waitFor（可能有多个并发等待者）
        const pending = this.resolvers.get(name);
        if (pending) {
            this.resolvers.delete(name);
            for (const r of pending) {
                r(this.services.get(name)!);
            }
        }
    }

    /**
     * 等待服务就绪。
     * 已 resolve（非 pending）则立即返回，避免 resolve-before-wait 死锁。
     * pending 则阻塞直到 resolve 被调用。支持多个调用者并发等待。
     */
    async waitFor(name: string): Promise<ServiceStatus> {
        const svc = this.services.get(name);
        if (svc && svc.status !== "pending") return svc;
        return new Promise<ServiceStatus>((resolve) => {
            const arr = this.resolvers.get(name) ?? [];
            arr.push(resolve);
            this.resolvers.set(name, arr);
        });
    }

    /** 获取服务状态（不阻塞）。 */
    get(name: string): ServiceStatus | undefined {
        return this.services.get(name);
    }
}
