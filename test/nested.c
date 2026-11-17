#include <stdio.h>
#include <unistd.h>

#define STEP(name)         \
    do {                   \
        printf(name "\n"); \
        fflush(stdout);    \
        sleep(1);          \
    } while (0)

void d(void)
{
    STEP("d");
}

void c(void)
{
    STEP("c");
    d();
}

void b(void)
{
    STEP("b");
    c();
}

void a(void)
{
    STEP("a");
    b();
}

int main(void)
{
    a();
    return 0;
}
