"""Pure-Python LZO1X decompressor (the format of Kodi's XBT texture bundles)."""


def decompress(src, out_len):
    dst = bytearray()
    ip = 0

    def copy_match(m_pos, n):
        if m_pos < 0:
            raise ValueError('lookbehind overrun')
        for i in range(n):
            dst.append(dst[m_pos + i])

    def run_len(t, base):
        nonlocal ip
        while src[ip] == 0:
            t += 255
            ip += 1
        t += base + src[ip]
        ip += 1
        return t

    state = 'start'
    t = 0
    while True:
        if state == 'start':
            t = src[ip]
            if t > 17:
                ip += 1
                t -= 17
                if t < 4:
                    dst += src[ip:ip + t]; ip += t
                    t = src[ip]; ip += 1
                    state = 'match'
                    continue
                dst += src[ip:ip + t]; ip += t
                state = 'first_literal_run'
                continue
            state = 'loop'
            continue
        if state == 'loop':
            t = src[ip]; ip += 1
            if t >= 16:
                state = 'match'
                continue
            if t == 0:
                t = run_len(t, 15)
            dst += src[ip:ip + t + 3]; ip += t + 3
            state = 'first_literal_run'
            continue
        if state == 'first_literal_run':
            t = src[ip]; ip += 1
            if t >= 16:
                state = 'match'
                continue
            m_pos = len(dst) - (1 + 0x0800) - (t >> 2) - (src[ip] << 2); ip += 1
            copy_match(m_pos, 3)
            state = 'match_done'
            continue
        if state == 'match':
            if t >= 64:
                m_pos = len(dst) - 1 - ((t >> 2) & 7) - (src[ip] << 3); ip += 1
                t = (t >> 5) - 1
                copy_match(m_pos, t + 2)
                state = 'match_done'
                continue
            elif t >= 32:
                t &= 31
                if t == 0:
                    t = run_len(t, 31)
                m_pos = len(dst) - 1 - ((src[ip] >> 2) + (src[ip + 1] << 6)); ip += 2
            elif t >= 16:
                m_pos = len(dst) - ((t & 8) << 11)
                t &= 7
                if t == 0:
                    t = run_len(t, 7)
                m_pos -= (src[ip] >> 2) + (src[ip + 1] << 6); ip += 2
                if m_pos == len(dst):
                    break
                m_pos -= 0x4000
            else:
                m_pos = len(dst) - 1 - (t >> 2) - (src[ip] << 2); ip += 1
                copy_match(m_pos, 2)
                state = 'match_done'
                continue
            copy_match(m_pos, t + 2)
            state = 'match_done'
            continue
        if state == 'match_done':
            t = src[ip - 2] & 3
            if t == 0:
                state = 'loop'
                continue
            dst += src[ip:ip + t]; ip += t
            t = src[ip]; ip += 1
            state = 'match'
            continue
    if len(dst) != out_len:
        raise ValueError('size %d != %d' % (len(dst), out_len))
    return bytes(dst)
