import io
import json
import os
import random
import string
import sys
import unittest
import uuid
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import proxy  # noqa: E402

SEED = 20261103
DRAWS = 200
TEXT = string.ascii_letters + string.digits + " 、。ぁあいうえおアイウエオ漢字テスト\n"


def rand_text(rng, lo=0, hi=40):
    return "".join(rng.choice(TEXT) for _ in range(rng.randint(lo, hi)))


def make_wav(rng, seconds, rates=(8000, 16000, 44100, 48000)):
    rate, ch = rng.choice(rates), rng.choice([1, 2])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * ch * int(rate * seconds))
    return buf.getvalue(), int(rate * seconds) / rate


def multipart(fields):
    boundary = "t-" + uuid.uuid4().hex
    out = bytearray()
    for name, data, filename in fields:
        disp = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
        out += f"--{boundary}\r\nContent-Disposition: {disp}\r\n\r\n".encode() + data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", bytes(out)


def fields_of(ctype, body):
    return [(name, part.get_payload(decode=True) or b"") for name, part in proxy.parse(ctype, body)]


def identity_wav(data, filename):
    return data, filename or "audio.wav", "audio/wav", False


class RebuildProperties(unittest.TestCase):
    def test_only_supported_fields_reach_upstream(self):
        rng = random.Random(SEED)
        extra = ["prompt", "temperature", "model", "timestamp_granularities[]", "x" + rand_text(rng, 1, 5).strip()]
        for _ in range(DRAWS):
            # 分割のしきい値の前後を多めに引く
            seconds = rng.choice([rng.uniform(0.1, 200), proxy.CHUNK_SECONDS + rng.uniform(-1, 1)])
            wav, actual = make_wav(rng, seconds, rates=(1000, 2000))
            kws = [rand_text(rng, 1, 10).replace("\n", "") or "k" for _ in range(rng.randint(0, 5))]
            fields = [("file", wav, "a.wav")]
            fields += [(rng.choice(extra), rand_text(rng).replace("\n", "").encode(), None) for _ in range(rng.randint(0, 4))]
            fields.append(("language", rng.choice([b"ja", b"en", b"auto"]), None))
            rng.shuffle(fields)

            ctype, body, _ = proxy.rebuild(*multipart(fields), kws=kws, to_wav=identity_wav)
            got = fields_of(ctype, body)
            names = [n for n, _ in got]

            self.assertTrue(set(names) <= proxy.PASS | {"keywords[]", "chunking_strategy"})
            self.assertEqual([v.decode() for n, v in got if n == "keywords[]"], kws)
            self.assertEqual([v for n, v in got if n == "file"], [wav])
            self.assertEqual("chunking_strategy" in names, actual > proxy.CHUNK_SECONDS)
            self.assertTrue(all(v in (b"ja", b"auto") for n, v in got if n == "language"))


class WavSecondsProperties(unittest.TestCase):
    def test_matches_written_duration(self):
        rng = random.Random(SEED)
        for _ in range(DRAWS):
            wav, actual = make_wav(rng, rng.uniform(0, 10))
            self.assertAlmostEqual(proxy.wav_seconds(wav), actual, places=6)

    def test_non_wav_is_none(self):
        rng = random.Random(SEED)
        for _ in range(DRAWS):
            data = bytes(rng.randrange(256) for _ in range(rng.randint(0, 64)))
            if data[:4] == b"RIFF":
                continue
            self.assertIsNone(proxy.wav_seconds(data))


class TranscriptProperties(unittest.TestCase):
    def test_returns_inside_of_last_user_transcript(self):
        rng = random.Random(SEED)
        for _ in range(DRAWS):
            t = rand_text(rng)
            # OpenWhispr は本文の前に <system-reminder> などのタグを付けて送る
            noise = f"<system-reminder>{rand_text(rng)}</system-reminder>" if rng.random() < 0.7 else rand_text(rng)
            content = f"{noise}<transcript>{t}</transcript>{rand_text(rng)}"
            if rng.random() < 0.5:
                content = [{"type": "text", "text": content}]
            msgs = [{"role": "system", "content": rand_text(rng)}, {"role": "user", "content": content}]
            body = json.dumps({"messages": msgs}).encode()
            self.assertEqual(proxy.extract_transcript(body), t.strip())

    def test_never_raises_on_garbage(self):
        rng = random.Random(SEED)
        for _ in range(DRAWS):
            body = bytes(rng.randrange(256) for _ in range(rng.randint(0, 64)))
            self.assertIsInstance(proxy.extract_transcript(body), str)


class KeywordProperties(unittest.TestCase):
    def test_keeps_entries_in_order_and_drops_comments_and_blanks(self):
        rng = random.Random(SEED)
        for _ in range(DRAWS):
            entries = [f"w{i}=" + rand_text(rng, 1, 8).replace("\n", "") for i in range(rng.randint(0, 8))]
            lines = []
            for e in entries:
                lines += rng.choice([[], ["", "# " + rand_text(rng).replace("\n", "")]])
                lines.append(" " * rng.randint(0, 2) + e)
            self.assertEqual(proxy.parse_keywords("\n".join(lines)), [e.strip() for e in entries])


if __name__ == "__main__":
    unittest.main()
