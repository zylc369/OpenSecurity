// sigwrap_tracer_test.c — sigwrap_tracer.c 的边界条件测试载体（回归用, v2）
// 编译: gcc -O0 -o sigwrap_test sigwrap_tracer_test.c
// 用法: ./sigwrap_test <gptr|max|page|mixed|ign|multi|nosiginfo|savere|unmapped>
// 断言（LD_PRELOAD=sigwrap.so 运行）:
//   gptr      → 日志含 S 行且内容为 state_buf 前 32 字节; exit=0
//   max       → exit=1 + 日志含 TOO_MANY + stderr 无 RESTORE_LEAK（_exit 丢 stdout 缓冲, 断言串走 stderr）
//   page      → exit=0 且 code hex 长度 18(页首 back=1)/30(页尾 fwd=7)
//   mixed     → 日志 s=5,4,8 各一次; exit=0
//   ign       → 日志仅 1 行 s=5（SIG_IGN 透传不包装; glibc signal() 不经 sigaction 拦截, 故先补一次注册触发日志初始化）
//   multi     → stderr 输出 WHICH=3（两个不同 handler 各自正确分发, 无交叉）
//   nosiginfo → 日志无 s=10 行（sa_handler 风格透传）+ stderr 输出 NSI=1（真 handler 仍执行）
//   savere    → exit=0 且日志 T# 行数 ≤3（oldact 修正, 无无限递归）+ stderr SAVED=1（恢复的是真 handler）
//   unmapped  → exit=0 且日志含 code=? 行（RIP 重定向未映射页不崩、有记录）
//   lowaddr   → exit=0 且日志无 S 行（GPTR 指向不可读地址 0x1000 时防御不崩）
//   altstack  → exit=0 且日志 1 行 s=5（SA_ONSTACK 注册在 alt stack 上正常包装记录）
// 注意: sigwrap 的 logf_init 在首次 sigaction 调用时读环境变量——所有 setenv 必须先于注册
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <sys/mman.h>
#include <unistd.h>
#include <setjmp.h>

static int n = 0, g_which = 0, g_nsi = 0, g_saved = 0;

static void h_trap(int sig, siginfo_t *i, void *u) { n++; g_which |= 1; }
static void h_ill(int sig, siginfo_t *i, void *u) {
    n++;
    g_which |= 2;
    // ud2 为 fault 类（RIP 指向自身），+2 跳过防无限循环
    ((ucontext_t *)u)->uc_mcontext.gregs[REG_RIP] += 2;
}
static void h_fpe(int sig, siginfo_t *i, void *u) {
    n++;
    ((ucontext_t *)u)->uc_mcontext.gregs[REG_RIP] += 2;
}
static void h_nsi(int sig) { g_nsi = 1; }             // sa_handler 风格（无 SA_SIGINFO）
static void h_save_a(int sig, siginfo_t *i, void *u) { g_saved = 1; }
static void h_save_b(int sig, siginfo_t *i, void *u) { g_saved = 2; }
static sigjmp_buf g_jb;
static void h_segv(int sig, siginfo_t *i, void *u) {  // unmapped 模式: siglongjmp 跳回（不依赖标签地址布局）
    siglongjmp(g_jb, 1);
}
static void h_redir(int sig, siginfo_t *i, void *u) { // unmapped 模式: RIP 重定向到未映射页
    ((ucontext_t *)u)->uc_mcontext.gregs[REG_RIP] = 0xdead0000ULL;
}

// gptr 模式: 模拟 VM 程序的全局 runtime 结构
static unsigned long long state_buf[8] = {0x1122334455667788ULL, 0x99aabbccddeeff00ULL, 2, 3, 4, 5, 6, 7};
static unsigned long long runtime_s[4] = {(unsigned long long)state_buf, 0xdead, 0xbeef, 0xcafe};
static unsigned long long *g_runtime = runtime_s;

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "gptr";
    char buf[64];

    if (!strcmp(mode, "gptr")) {
        snprintf(buf, sizeof buf, "0x%llx", (unsigned long long)(unsigned long)&g_runtime);
        setenv("SIGWRAP_GPTR", buf, 1);
        setenv("SIGWRAP_DSTATE", "32", 1);
    } else if (!strcmp(mode, "lowaddr")) {
        setenv("SIGWRAP_GPTR", "0x1000", 1);   // 不可读低地址——wrapper 内解引用应被防御
        setenv("SIGWRAP_DSTATE", "32", 1);
    } else if (!strcmp(mode, "max")) {
        setenv("SIGWRAP_MAX", "2", 1);
    }

    struct sigaction sa = {0};
    sa.sa_flags = SA_SIGINFO;

    if (!strcmp(mode, "ign")) {
        signal(SIGUSR1, SIG_IGN);   // SIG_IGN 不应被包装（透传分支; 注意 glibc signal() 不经 sigaction 拦截）
        raise(SIGUSR1);
        // 补一次真 sigaction 注册: 触发拦截器初始化（否则日志文件不创建, 无从断言）
        sa.sa_sigaction = h_trap; sigaction(SIGTRAP, &sa, NULL);
        __asm__ volatile("int3");
        puts("ign_end");
        return 0;
    }
    if (!strcmp(mode, "nosiginfo")) {
        struct sigaction s2 = {0};
        s2.sa_handler = h_nsi;      // 无 SA_SIGINFO——应透传不包装, 但 handler 正常执行
        sigaction(SIGUSR1, &s2, NULL);
        raise(SIGUSR1);
        fprintf(stderr, "NSI=%d\n", g_nsi);
        return 0;
    }
    if (!strcmp(mode, "multi")) {
        sa.sa_sigaction = h_trap; sigaction(SIGTRAP, &sa, NULL);
        sa.sa_sigaction = h_ill;  sigaction(SIGILL, &sa, NULL);
        __asm__ volatile("int3");
        __asm__ volatile("ud2");
        fprintf(stderr, "WHICH=%d\n", g_which);   // 3 = 两个 handler 各自正确跑
        return 0;
    }
    if (!strcmp(mode, "savere")) {
        sa.sa_sigaction = h_save_a; sigaction(SIGTRAP, &sa, NULL);
        struct sigaction old = {0};
        sa.sa_sigaction = h_save_b; sigaction(SIGTRAP, &sa, &old);   // old 应含真 handler h_save_a（非 wrapper）
        sigaction(SIGTRAP, &old, NULL);                               // 恢复——若 old 是 wrapper 则无限递归
        __asm__ volatile("int3");                                     // 应跑 h_save_a
        fprintf(stderr, "SAVED=%d\n", g_saved);                       // 1 = 恢复的是真 handler
        return 0;
    }
    if (!strcmp(mode, "unmapped")) {
        sa.sa_sigaction = h_segv;  sigaction(SIGSEGV, &sa, NULL);
        sa.sa_sigaction = h_redir; sigaction(SIGTRAP, &sa, NULL);
        if (sigsetjmp(g_jb, 1) == 0) {
            __asm__ volatile("int3");  // h_redir 把 RIP 改到 0xdead0000 → 取指 SIGSEGV(fault, RIP=0xdead0000)
            return 1;                  // 不应到达
        }
        puts("unmapped_end");          // h_segv 经 siglongjmp 跳回此处
        return 0;
    }

    if (!strcmp(mode, "altstack")) {
        stack_t ss;
        ss.ss_sp = malloc(SIGSTKSZ * 4);
        ss.ss_size = SIGSTKSZ * 4;
        ss.ss_flags = 0;
        if (sigaltstack(&ss, NULL) != 0) { perror("sigaltstack"); return 1; }
        sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
        sa.sa_sigaction = h_trap; sigaction(SIGTRAP, &sa, NULL);
        __asm__ volatile("int3");
        puts("altstack_end");
        return 0;
    }

    // 通用注册（gptr/lowaddr/max/page/mixed）
    sa.sa_sigaction = h_trap; sigaction(SIGTRAP, &sa, NULL);
    sa.sa_sigaction = h_ill;  sigaction(SIGILL, &sa, NULL);
    sa.sa_sigaction = h_fpe;  sigaction(SIGFPE, &sa, NULL);

    if (!strcmp(mode, "gptr") || !strcmp(mode, "lowaddr")) {
        __asm__ volatile("int3");
        puts("gptr_done");
    } else if (!strcmp(mode, "max")) {
        __asm__ volatile("int3"); fprintf(stderr, "MAX1\n");
        __asm__ volatile("int3"); fprintf(stderr, "MAX2\n");
        __asm__ volatile("int3"); fprintf(stderr, "RESTORE_LEAK\n");   // stderr 无缓冲——_exit 前必达, 断言有效
        fprintf(stderr, "RESTORE_LEAK2\n");
    } else if (!strcmp(mode, "page")) {
        unsigned char *p = mmap(NULL, 0x2000, PROT_READ|PROT_WRITE|PROT_EXEC,
                                MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
        if (p == MAP_FAILED) { perror("mmap"); return 1; }
        if (munmap(p + 0x1000, 0x1000) != 0) { perror("munmap"); return 1; }
        p[0] = 0xCC; p[1] = 0xC3;
        ((void(*)())p)();
        puts("page_head_ok");
        unsigned char *q = p + 0xFF8;                 // 第 1 页尾（0x1FF8 是已 munmap 的第 2 页）
        q[0] = 0xCC; q[1] = 0xC3;
        ((void(*)())q)();
        puts("page_tail_ok");
    } else if (!strcmp(mode, "mixed")) {
        __asm__ volatile("int3");   puts("mix_trap");
        __asm__ volatile("ud2");    puts("mix_ill");
        volatile int zero = 0, one = 1, r;
        r = one / zero;             (void)r;
        puts("mix_fpe");
    }
    printf("%s_end exit0\n", mode);
    return 0;
}
