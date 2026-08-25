"""
Sun/moon math shared by the Almanac screen. Sunrise/sunset uses the same
`astral` library already relied on for EC day/night icon selection
(see adapters/ec.py) -- real astronomical calculation, not a guess.

Moon phase *dates* (WS4KP's Almanac shows the next 4 upcoming quarter
events -- New/First/Full/Last -- not "today's phase", confirmed live via
DOM inspection) are computed from the synodic month length against a known
reference new moon, rather than pulled from an API: this is the same kind
of accuracy tradeoff as the Hourly-Forecast icon-set simplification
elsewhere in this project -- a fixed-length-month approximation drifts by
at most a few hours over any date range worth displaying, well within
whole-day display precision.
"""
from datetime import datetime, timedelta, timezone

from astral import LocationInfo
from astral.sun import sun

SYNODIC_MONTH_DAYS = 29.530588853
REFERENCE_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)

PHASE_SEQUENCE = [('New', 0.0), ('First', 0.25), ('Full', 0.5), ('Last', 0.75)]
PHASE_ICON = {'New': 'New-Moon', 'First': 'First-Quarter', 'Full': 'Full-Moon', 'Last': 'Last-Quarter'}


def sunrise_sunset(lat, lon, date, tz):
	"""Returns (sunrise_str, sunset_str) in '%-I:%M %p' local time, or
	('--', '--') for a location/date with no real sunrise or sunset (polar
	day/night) -- astral raises for that case rather than returning None."""
	loc = LocationInfo(latitude=lat, longitude=lon, timezone=str(tz))
	try:
		s = sun(loc.observer, date=date, tzinfo=tz)
	except ValueError:
		return '--', '--'
	return _fmt(s['sunrise']), _fmt(s['sunset'])


def _fmt(dt):
	return dt.strftime('%-I:%M %p') if hasattr(dt, 'strftime') else str(dt)


def fetch_almanac(lat, lon, tz):
	"""Assembles the full data dict screens.almanac.render() expects: today +
	tomorrow's sunrise/sunset (WS4KP's widescreen layout only shows 2 of its
	3 DOM columns, confirmed live -- see layout.ALMANAC's docstring) and the
	next 4 upcoming moon-quarter events."""
	today = datetime.now(tz).date()
	days = []
	for offset, day_name in ((0, datetime.now(tz).strftime('%A')), (1, (datetime.now(tz) + timedelta(days=1)).strftime('%A'))):
		date = today + timedelta(days=offset)
		sunrise, sunset = sunrise_sunset(lat, lon, date, tz)
		days.append({'day_name': day_name, 'sunrise': sunrise, 'sunset': sunset})
	return {'days': days, 'moon_events': upcoming_moon_phases(today)}


def upcoming_moon_phases(from_date, count=4):
	"""Returns the next `count` quarter-moon events after from_date, each
	{'type': 'New'|'First'|'Full'|'Last', 'date': 'Aug 20', 'icon': <name>}."""
	now = datetime.combine(from_date, datetime.min.time(), tzinfo=timezone.utc)
	age_days = (now - REFERENCE_NEW_MOON).total_seconds() / 86400
	events = []
	cycle_start = now - timedelta(days=(age_days % SYNODIC_MONTH_DAYS))
	cycle = 0
	while len(events) < count:
		for phase_name, phase_frac in PHASE_SEQUENCE:
			event_time = cycle_start + timedelta(days=SYNODIC_MONTH_DAYS * (cycle + phase_frac))
			if event_time <= now:
				continue
			events.append({'type': phase_name, 'date': event_time.strftime('%b %-d'), 'icon': PHASE_ICON[phase_name]})
			if len(events) == count:
				break
		cycle += 1
	return events
