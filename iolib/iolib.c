#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

uint64_t iommap(const char *dev_path, uint64_t size, int readonly) {
    const int fd = open(dev_path, readonly ? O_RDONLY : O_RDWR);
    if (fd == -1) {
        perror("failed to open cmn device\n");
        exit(1);
    }

    const int prot = readonly ? PROT_READ : (PROT_READ | PROT_WRITE);
    void *base = mmap(NULL, (size_t)size, prot, MAP_SHARED, fd, 0);
    close(fd);
    if (base == MAP_FAILED) {
        perror("failed to map cmn register space\n");
        exit(1);
    }

    return (uint64_t)base;
}

uint64_t ioread(uint64_t addr) {
    volatile uint64_t *paddr = (volatile uint64_t *)addr;
    return *paddr;
}

void iowrite(uint64_t addr, uint64_t value) {
    volatile uint64_t *paddr = (volatile uint64_t *)addr;
    *paddr = value;
}
