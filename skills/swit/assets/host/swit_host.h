/* swit_host.h - helpers shared by host-side SWE.5 integration tests (copied into host/support/).
 *
 * Timing is judged in scheduler ticks driven by the test, never in host wall-clock time.
 */
#ifndef SWIT_HOST_H
#define SWIT_HOST_H

/* Call a periodic entry point n times (one call = one scheduler period of that task). */
#define SWIT_RUN_CYCLES(task_fn, n)                                              \
    do {                                                                         \
        unsigned swit_i_;                                                        \
        for (swit_i_ = 0u; swit_i_ < (unsigned)(n); ++swit_i_) { task_fn(); }    \
    } while (0)

/* Call task_fn until cond becomes true or limit calls were made; 'used' receives the count.
 * Use it to measure debounce / timeout windows in ticks and to run stateful filters to steady state. */
#define SWIT_RUN_UNTIL(task_fn, cond, limit, used)                               \
    do {                                                                         \
        (used) = 0u;                                                             \
        while (!(cond) && ((used) < (unsigned)(limit))) { task_fn(); ++(used); } \
    } while (0)

#endif /* SWIT_HOST_H */
