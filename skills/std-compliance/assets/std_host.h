/* std_host.h - helpers for host-side protocol behaviour tests (copied into host/support/).
 *
 * Time is counted in scheduler ticks driven by the test, never host wall-clock time. A timeout of
 * 1000 ms on a 5 ms MainFunction is 200 calls; assert on call counts, not on elapsed seconds.
 */
#ifndef STD_HOST_H
#define STD_HOST_H

/* Call a periodic entry point n times (one call = one period of that MainFunction). */
#define STD_RUN_CYCLES(task_fn, n)                                               \
    do {                                                                         \
        unsigned std_i_;                                                         \
        for (std_i_ = 0u; std_i_ < (unsigned)(n); ++std_i_) { task_fn(); }       \
    } while (0)

/* Call task_fn until cond is true or limit calls were made; 'used' receives the count. */
#define STD_RUN_UNTIL(task_fn, cond, limit, used)                                \
    do {                                                                         \
        (used) = 0u;                                                             \
        while (!(cond) && ((used) < (unsigned)(limit))) { task_fn(); ++(used); } \
    } while (0)

/* Milliseconds -> number of calls of a MainFunction with the given period (rounded up). */
#define STD_MS_TO_CYCLES(ms, period_ms) (((ms) + (period_ms) - 1u) / (period_ms))

#endif /* STD_HOST_H */
