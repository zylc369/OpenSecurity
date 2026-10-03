// sigwrap_tracer.c — LD_PRELOAD 信号处理器包装追踪器 (v3)
//
// 用途: 目标程序用 sigaction 注册信号 handler 作 VM dispatcher（SIGTRAP/SIGILL/SIGFPE 等）
// 时，本包装器拦截 sigaction 捕获该 handler，改为先 dump 上下文再调用，返回后再 dump 一次
// —— 一次运行拿到全部 trap 序列（全 gregs、RIP 前后指令字节、handler 对 RIP/EFL 的改写）。
// 配合 vm-bytecode-reversing.md §1a 使用。Unicorn 模拟含信号/TF/SMC 的目标不可行时首选本方案。
//
// 编译: gcc -shared -fPIC -O2 -o sigwrap.so sigwrap_tracer.c -ldl
// 使用: LD_PRELOAD=./sigwrap.so SIGWRAP_LOG=/tmp/t.log ./target
// 平台: 仅 x86-64 Linux（依赖 ucontext gregs/REG_* 宏）; 其他架构不编译，勿使用
//
// 环境变量:
//   SIGWRAP_LOG=/path        输出文件（默认 /tmp/sigwrap.log）
//   SIGWRAP_MAX=N            trap 上限，超过后 _exit(1) 防日志爆炸（默认 3000000）
//   SIGWRAP_GPTR=0xADDR      全局指针地址（hex）——程序把 VM runtime 状态挂在全局变量时，
//                            每 trap 追加 dump *(u64*)GPTR 指向的结构（如 state 指针数组）
//   SIGWRAP_STATE_OFF=N      GPTR 结构内 state 指针的偏移（十进制，默认 0）
//   SIGWRAP_DSTATE=N         dump state 指向地址的前 N 字节 hex（默认 0=不 dump）
//
// 输出行格式:
//   T#<n> s=<sig> rip=<rip> code=<rip 前 8 后 8 字节; 不可读页为 ?> <gregs: r8-r15,rdi,rsi,rax,rbx,rcx,rdx,rbp,rsp> efl=<efl>
//   [S <state_addr> <hex...>]                          — SIGWRAP_GPTR/DSTATE 配置时的 state dump
//   -> rip=<newrip> efl=<newefl>                       — 真 handler 返回后（观察 RIP 重定向/TF 置位）
//
// 正确性设计（勿回退）:
//   1. 每信号独立 handler 槽——不同信号注册不同 handler 时不交叉分发
//   2. 仅包装 SA_SIGINFO 注册——sa_handler 风格（无 SA_SIGINFO）时 uctx 参数不确定，透传
//   3. oldact 修正——查询结果中的 wrapper 换回真实 handler，防保存/恢复模式无限递归
//   4. code/state 字节经 /proc/self/mem pread 读取——handler 把 RIP 重定向到未映射页时不崩
//      （trace 不在最 interesting 的时刻断掉）
//   5. stdio 缓冲在 sigaction（正常上下文）预分配——首次 trap 打断目标 malloc 不会死锁
//   6. glibc 内部信号 32/33（SIGCANCEL/SIGSETXID）不包装; 实时信号（SIGRTMIN 起）正常包装
//
// 已知限制（使用前知悉）:
//   - glibc 的 signal() 不经 sigaction 符号拦截——用 signal() 注册的 handler 不被观测（目标运行不受影响）;
//     需要观测时把目标改为 sigaction 注册或用 LD_PRELOAD 同时拦截 signal
//   - 多线程目标: 每信号槽保证分发正确性, 但多线程 trap 的日志行可能交错（按 T# 序号不可全序解释）
//   - code= 与 S 行经 /proc/self/mem 读取, 内核不支持该接口时降级为 ?（trace 不断）

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <ucontext.h>
#include <dlfcn.h>
#include <unistd.h>
#include <fcntl.h>

#define SIGWRAP_MAXSIG 65   // 覆盖标准+实时信号

static void (*real_handlers[SIGWRAP_MAXSIG])(int, siginfo_t *, void *) = {0};
static FILE *logf = NULL;
static long trap_count = 0;
static long max_traps = 3000000;
static unsigned long long *gptr = NULL;
static long state_off = 0;
static long dstate_len = 0;
static int memfd = -1;     // /proc/self/mem，安全读任意地址

// 库加载时（单线程上下文）预初始化: fopen/malloc/open 均安全，且 stdio 缓冲预分配
// 消除多线程目标首次 sigaction 并发调 logf_init 的 fopen 竞态
__attribute__((constructor)) static void sigwrap_ctor(void) {
    const char *lf = getenv("SIGWRAP_LOG");
    logf = fopen(lf ? lf : "/tmp/sigwrap.log", "w");
    if (logf) {
        fprintf(logf, "# sigwrap_tracer v3\n");
        fflush(logf);
    }
    memfd = open("/proc/self/mem", O_RDONLY);
}

// 运行期参数补读（幂等, 纯 getenv/atoi 无 malloc——目标可能用 setenv 在运行中配置 GPTR/MAX 等）
static void env_late(void) {
    const char *m = getenv("SIGWRAP_MAX");
    if (m) max_traps = atol(m);
    const char *gp = getenv("SIGWRAP_GPTR");
    if (gp) gptr = (unsigned long long *)strtoull(gp, NULL, 0);
    const char *so = getenv("SIGWRAP_STATE_OFF");
    if (so) state_off = atol(so);
    const char *ds = getenv("SIGWRAP_DSTATE");
    if (ds) dstate_len = atol(ds);
}

// 经 /proc/self/mem 读任意地址; 未映射页返回 0（不崩溃）。信号上下文安全（pread 为纯 syscall）。
static int safe_read(unsigned long long addr, void *out, unsigned long n) {
    if (memfd < 0) return 0;
    return pread(memfd, out, n, (off_t)addr) == (ssize_t)n;
}

#define REG(x) (unsigned long long)uc->uc_mcontext.gregs[REG_##x]

static void dump_state_line(void) {
    if (!gptr || dstate_len <= 0) return;
    unsigned long long runtime = 0;
    if (!safe_read((unsigned long long)(unsigned long)gptr, &runtime, sizeof runtime)) return;  // GPTR 指向不可读地址时不崩
    if (runtime < 0x1000) return;
    unsigned long long state = 0;
    if (!safe_read(runtime + (unsigned long long)state_off, &state, sizeof state)) return;
    if (state < 0x1000) return;
    unsigned char buf[256];
    if (dstate_len > (long)sizeof buf) dstate_len = sizeof buf;
    if (!safe_read(state, buf, (unsigned long)dstate_len)) return;
    fprintf(logf, "S %llx ", state);
    for (long i = 0; i < dstate_len; i++) fprintf(logf, "%02x", buf[i]);
    fprintf(logf, "\n");
}

static void wrapper_handler(int sig, siginfo_t *info, void *uctx) {
    ucontext_t *uc = (ucontext_t *)uctx;
    trap_count++;
    // 注意: 文件/memfd 初始化在库 constructor（单线程上下文）已完成; 运行期参数由 sigaction 拦截时的 env_late 补读。
    // logf 仍为 NULL 时跳过 dump（仅计数），保证不因追踪器自身崩溃。
    if (logf) {
        unsigned long long rip = REG(RIP);
        fprintf(logf, "T#%ld s=%d rip=%llx code=", trap_count, sig, rip);
        // 前 8 后 8 字节; 双向截断在 4K 页边界内 + pread 安全读（页未映射输出 ?，trace 不中断）
        long back = 8, fwd = 8;
        unsigned long inpage = (unsigned long)rip & 0xFFF;
        if (inpage < 8) back = (long)inpage;
        if (0x1000 - inpage < 8) fwd = (long)(0x1000 - inpage);
        unsigned char cb[16];
        unsigned char ok = safe_read(rip - (unsigned long long)back, cb, (unsigned long)(back + fwd));
        if (ok) { for (long i = 0; i < back + fwd; i++) fprintf(logf, "%02x", cb[i]); }
        else fprintf(logf, "?");
        fprintf(logf, " r8=%llx r9=%llx r10=%llx r11=%llx r12=%llx r13=%llx r14=%llx r15=%llx"
                      " rdi=%llx rsi=%llx rax=%llx rbx=%llx rcx=%llx rdx=%llx rbp=%llx rsp=%llx efl=%llx\n",
                REG(R8), REG(R9), REG(R10), REG(R11), REG(R12), REG(R13), REG(R14), REG(R15),
                REG(RDI), REG(RSI), REG(RAX), REG(RBX), REG(RCX), REG(RDX), REG(RBP), REG(RSP),
                REG(EFL));
        dump_state_line();
        fflush(logf);
        if (trap_count > max_traps) { fprintf(logf, "TOO_MANY\n"); fflush(logf); _exit(1); }
    }
    // 每信号分发——不同信号各自注册的 handler 互不串扰
    void (*rh)(int, siginfo_t *, void *) =
        (sig >= 1 && sig < SIGWRAP_MAXSIG) ? real_handlers[sig] : NULL;
    if (rh)
        rh(sig, info, uctx);
    if (logf) {
        fprintf(logf, "-> rip=%llx efl=%llx\n", REG(RIP), REG(EFL));
        fflush(logf);
    }
}

int sigaction(int signum, const struct sigaction *act, struct sigaction *oldact) {
    static int (*real_sigaction)(int, const struct sigaction *, struct sigaction *) = NULL;
    if (!real_sigaction)
        real_sigaction = dlsym(RTLD_NEXT, "sigaction");
    env_late();
    if (act && (act->sa_flags & SA_SIGINFO) && act->sa_sigaction
        // 防 self-restore 重装: 目标若把我们返回的（已修正的）handler 装回，此处值是真 handler，
        // 不会等于 wrapper; 若目标从别处拿到 wrapper 地址强行装，透传防递归
        && act->sa_sigaction != (void *)wrapper_handler
        && (void *)act->sa_sigaction != (void *)SIG_DFL
        && (void *)act->sa_sigaction != (void *)SIG_IGN
        && signum > 0 && signum < SIGWRAP_MAXSIG
        && signum != 32 && signum != 33) {   // glibc 内部信号 SIGCANCEL/SIGSETXID 不包装; 实时信号(>=SIGRTMIN)正常包装
        void (*prev)(int, siginfo_t *, void *) = real_handlers[signum];
        real_handlers[signum] = act->sa_sigaction;
        struct sigaction modified = *act;
        modified.sa_sigaction = wrapper_handler;
        int ret = real_sigaction(signum, &modified, oldact);
        if (ret == 0 && oldact && oldact->sa_sigaction == (void *)wrapper_handler) {
            // 内核视角的旧动作是 wrapper——换回它之前记录的真实 handler，
            // 防保存/恢复模式把 wrapper 当真 handler 重装导致无限递归
            oldact->sa_sigaction = prev;
        }
        return ret;
    }
    return real_sigaction(signum, act, oldact);
}
