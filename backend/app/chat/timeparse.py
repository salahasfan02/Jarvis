"""Durations and clock times as people say them.

  duration("1 hour 20 minutes") -> 4800      duration("half an hour") -> 1800
  when("6pm") / when("at 6") / when("tomorrow at 9:30") / when("tonight at 8") -> datetime

A bare "at 6" means the next 6 o'clock to come (6 pm in the afternoon, 6 am
just after midnight); with a day, 1-6 o'clock means the afternoon ("tomorrow
at 3" is 3 pm) and 7-11 the morning.
"""
from __future__ import annotations

import datetime
import re

_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
        "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45,
        "forty-five": 45, "sixty": 60, "ninety": 90, "a couple of": 2, "a few": 3}
_UNIT = {"h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
         "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
         "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1}
_NUM_RE = r"(?:\d+(?:\.\d+)?|" + "|".join(sorted(map(re.escape, _NUM), key=len, reverse=True)) + ")"
_PART = re.compile(rf"({_NUM_RE})\s*-?\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b"
                   rf"(\s+and\s+a\s+half)?")


def _num(s: str) -> float:
    s = s.strip().lower()
    return float(s) if re.fullmatch(r"\d+(?:\.\d+)?", s) else float(_NUM.get(s, 0))


def duration(text: str) -> float | None:
    """Seconds in '10 minutes', '1h 30m', 'an hour and a half', 'half an hour'."""
    t = text.lower().strip()
    t = re.sub(r"^(?:for|in)\s+", "", t)
    if re.fullmatch(r"half\s+an?\s+hour", t):
        return 1800.0
    if re.fullmatch(r"(?:a\s+)?quarter\s+of\s+an\s+hour", t):
        return 900.0
    total, pos = 0.0, 0
    for m in _PART.finditer(t):
        between = t[pos:m.start()].strip(" ,")
        if between and between not in ("and",):
            return None
        value = _num(m.group(1)) * _UNIT[m.group(2)]
        if m.group(3):
            value += 0.5 * _UNIT[m.group(2)]
        total += value
        pos = m.end()
    if t[pos:].strip(" ,"):
        if re.fullmatch(r"and\s+a\s+half", t[pos:].strip()) and total:
            total *= 1.5 if total in (3600.0, 60.0) else 1
        else:
            return None
    return total or None


_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_CLOCK = re.compile(r"(?:at\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?$")


def when(text: str, now: datetime.datetime | None = None) -> datetime.datetime | None:
    """A clock time with an optional day: '6pm', 'at 6', 'tomorrow at 9:30',
    'tonight at 8', 'on friday at 10am', 'noon'."""
    now = now or datetime.datetime.now()
    t = text.lower().strip().strip(",")
    day: datetime.date | None = None
    evening = False
    for word, delta in (("today", 0), ("tonight", 0), ("tomorrow", 1)):
        if re.search(rf"\b{word}\b", t):
            day = (now + datetime.timedelta(days=delta)).date()
            evening = word == "tonight"
            t = re.sub(rf"\b{word}\b", "", t).strip()
    for i, name in enumerate(_DAYS):
        if re.search(rf"\b(?:on\s+)?{name}\b", t):
            ahead = (i - now.weekday()) % 7 or 7
            day = (now + datetime.timedelta(days=ahead)).date()
            t = re.sub(rf"\b(?:on\s+)?{name}\b", "", t).strip()
    t = re.sub(r"\s+", " ", t).strip()
    if t in ("noon", "at noon", "midday", "at midday"):
        hour, minute, ampm = 12, 0, "pm"
    elif t in ("midnight", "at midnight"):
        hour, minute, ampm = 0, 0, "am"
    else:
        m = _CLOCK.fullmatch(t)
        if not m:
            return None
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        ampm = (m.group(3) or "").replace(".", "")
    if hour > 23 or minute > 59:
        return None
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    elif not ampm and hour <= 12 and (evening or day is None or 1 <= hour <= 6):
        if (evening or day is not None) and hour < 12:
            hour += 12          # "tonight at 8", "tomorrow at 3" (3 pm, not 3 am)
        elif day is None:
            # "at 6": the next 6 o'clock to come.
            today_am = now.replace(hour=hour % 12, minute=minute, second=0, microsecond=0)
            for cand in (today_am, today_am + datetime.timedelta(hours=12),
                         today_am + datetime.timedelta(hours=24)):
                if cand > now:
                    return cand
    base = day or now.date()
    result = datetime.datetime.combine(base, datetime.time(hour, minute))
    if day is None and result <= now:
        result += datetime.timedelta(days=1)
    return result
