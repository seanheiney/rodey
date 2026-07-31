/*
 * Observational interposer for the RODECaster App.
 *
 * Logs every IOHIDDeviceSetReport the app makes, then calls through unchanged.
 * This reveals the real host->device command framing - including the handshake
 * that starts the notification stream - without us sending anything to the board.
 *
 * Needed because macOS on Apple Silicon has no USB capture interface, and the
 * app ships with hardened runtime (so it must be re-signed ad-hoc to allow this).
 *
 * build:
 *   clang -arch arm64 -dynamiclib -framework IOKit -framework CoreFoundation \
 *         -o hidlog.dylib hidlog.c
 */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <pthread.h>
#include <IOKit/hid/IOHIDDevice.h>

#define LOGPATH "/tmp/rode-hidlog.txt"

static pthread_mutex_t lk = PTHREAD_MUTEX_INITIALIZER;
static FILE *lf = NULL;

static void ensure_log(void) {
    if (!lf) {
        lf = fopen(LOGPATH, "a");
        if (lf) {
            setvbuf(lf, NULL, _IOLBF, 0);
            fprintf(lf, "\n=== hidlog attached ===\n");
        }
    }
}

static void dump(const char *tag, CFIndex reportID, const uint8_t *b, CFIndex n) {
    pthread_mutex_lock(&lk);
    ensure_log();
    if (lf) {
        struct timespec ts;
        clock_gettime(CLOCK_REALTIME, &ts);
        double t = ts.tv_sec + ts.tv_nsec / 1e9;

        /* trim trailing zero padding so the real frame is readable */
        CFIndex end = n;
        while (end > 0 && b[end - 1] == 0) end--;

        fprintf(lf, "[%.3f] %s reportID=%ld len=%ld payload=%ld\n",
                t, tag, (long)reportID, (long)n, (long)end);
        fprintf(lf, "    hex  :");
        for (CFIndex i = 0; i < end && i < 64; i++) fprintf(lf, " %02x", b[i]);
        fprintf(lf, "\n    ascii: ");
        for (CFIndex i = 0; i < end && i < 64; i++)
            fputc((b[i] >= 32 && b[i] < 127) ? b[i] : '.', lf);
        fputc('\n', lf);
    }
    pthread_mutex_unlock(&lk);
}

IOReturn my_IOHIDDeviceSetReport(IOHIDDeviceRef device,
                                 IOHIDReportType reportType,
                                 CFIndex reportID,
                                 const uint8_t *report,
                                 CFIndex reportLength) {
    dump(reportType == kIOHIDReportTypeOutput ? "OUT" :
         reportType == kIOHIDReportTypeFeature ? "FEATURE" : "OTHER",
         reportID, report, reportLength);
    return IOHIDDeviceSetReport(device, reportType, reportID, report, reportLength);
}

IOReturn my_IOHIDDeviceGetReport(IOHIDDeviceRef device,
                                 IOHIDReportType reportType,
                                 CFIndex reportID,
                                 uint8_t *report,
                                 CFIndex *pReportLength) {
    IOReturn r = IOHIDDeviceGetReport(device, reportType, reportID, report, pReportLength);
    if (r == kIOReturnSuccess && pReportLength)
        dump("IN ", reportID, report, *pReportLength);
    return r;
}

typedef struct { const void *replacement; const void *replacee; } interpose_t;

__attribute__((used)) static const interpose_t interposers[]
__attribute__((section("__DATA,__interpose"))) = {
    { (const void *)my_IOHIDDeviceSetReport, (const void *)IOHIDDeviceSetReport },
    { (const void *)my_IOHIDDeviceGetReport, (const void *)IOHIDDeviceGetReport },
};
