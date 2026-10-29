#pragma once

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cinttypes>
#include <limits>

// Pure bounded protocol state, also compiled by native regression tests.
class RecoverySession {
public:
    explicit RecoverySession(const char* boot) { std::snprintf(boot_, sizeof(boot_), "%s", boot); }

    bool active(uint64_t now) {
        if (now < last_time_ || (active_ && now - last_request_ >= 750)) active_ = false;
        last_time_ = now;
        return active_;
    }

    // Return true only for a newly accepted HELLO (caller resets held inputs).
    bool command(const char* line, uint64_t now, char* output, size_t size) {
        output[0] = 0;
        active(now);
        if (std::strlen(line) >= 128) return false;
        char copy[128];
        std::strcpy(copy, line);
        char* fields[5] = {};
        unsigned count = 1;
        fields[0] = copy;
        for (char* p = copy; *p; ++p) {
            if (*p == ' ') {
                if (count == 5 || p == copy || p[-1] == 0 || p[1] == 0) return false;
                *p = 0;
                fields[count++] = p + 1;
            } else if (static_cast<unsigned char>(*p) < 33 || static_cast<unsigned char>(*p) > 126) return false;
        }
        if (count < 3 || std::strcmp(fields[0], "RTCTRL/2") || !hex_nonce(fields[2])) return false;
        if (count == 3 && !std::strcmp(fields[1], "HELLO")) {
            if (active_ && !std::strcmp(nonce_, fields[2])) return false;
            std::strcpy(nonce_, fields[2]);
            sequence_ = request_id_ = 0;
            active_ = true;
            last_request_ = now;
            std::snprintf(output, size, "RTCTRL/2 READY %s %s 2.0.0 0 %" PRIu64 "\n", nonce_, boot_, now);
            return true;
        }
        uint64_t request = 0;
        if (count == 4 && !std::strcmp(fields[1], "PING") && active_ &&
            !std::strcmp(nonce_, fields[2]) && number(fields[3], request) && request > request_id_) {
            request_id_ = request;
            last_request_ = now;
            std::snprintf(output, size, "RTCTRL/2 PONG %s %s %" PRIu64 " %" PRIu64 " %" PRIu64 "\n", nonce_, boot_, request, sequence_, now);
        }
        return false;
    }

    bool event(const char* input, uint64_t now, char* output, size_t size) {
        output[0] = 0;
        if (!active(now)) return false;
        if (sequence_ == std::numeric_limits<uint64_t>::max()) { active_ = false; return false; }
        ++sequence_;
        std::snprintf(output, size, "RTCTRL/2 EVENT %s %s %" PRIu64 " %" PRIu64 " %s\n", nonce_, boot_, sequence_, now, input);
        return true;
    }

private:
    static bool hex_nonce(const char* value) {
        if (std::strlen(value) != 32) return false;
        for (unsigned i = 0; i < 32; ++i) if (!((value[i] >= '0' && value[i] <= '9') || (value[i] >= 'a' && value[i] <= 'f'))) return false;
        return true;
    }
    static bool number(const char* value, uint64_t& result) {
        if (!*value || (value[0] == '0' && value[1])) return false;
        result = 0;
        for (const char* p = value; *p; ++p) {
            if (*p < '0' || *p > '9') return false;
            const unsigned digit = static_cast<unsigned>(*p - '0');
            if (result > (std::numeric_limits<uint64_t>::max() - digit) / 10) return false;
            result = result * 10 + digit;
        }
        return true;
    }
    char boot_[17] = {};
    char nonce_[33] = {};
    bool active_ = false;
    uint64_t sequence_ = 0;
    uint64_t request_id_ = 0;
    uint64_t last_request_ = 0;
    uint64_t last_time_ = 0;
};
