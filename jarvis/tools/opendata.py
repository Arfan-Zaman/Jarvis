"""Free, open, keyless data services JARVIS uses directly: no Claude, no account, no cost.

- open.weather    Open-Meteo (open-source forecast API): now and the next days, for any place.
- open.currency   Frankfurter (open-source, ECB rates), then open.er-api.com for the rest: convert currencies.
- open.holidays   Nager.Date (open-source): public holidays by country (and state) and year.
- open.vin        NHTSA vPIC (US government, public): decode a vehicle VIN (make, model, year, engine...).
- open.define     Free Dictionary API (open-source): meanings, examples and pronunciation of a word.
- open.news       Google News RSS: latest headlines on any topic, with their links.

All are read-only (permission `web_read`) and talk only to these fixed addresses.
"""

from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET

from ..common import ValidationError
from ..safety import ActionCategory
from .registry import Tool, ToolRegistry
from .web import WebError, _get, _json

WEATHER_CODES = {0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
                 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain",
                 65: "heavy rain", 71: "light snow", 73: "snow", 75: "heavy snow", 80: "showers",
                 81: "showers", 82: "heavy showers", 95: "thunderstorm", 96: "thunderstorm with hail",
                 99: "thunderstorm with hail"}


def _text(inputs, key, required=True, limit=120) -> str:
    value = " ".join(str(inputs.get(key) or "").split())[:limit]
    if required and not value:
        raise ValidationError(f"{key} is required")
    return value


def _place(name: str) -> dict:
    data = _json("https://geocoding-api.open-meteo.com/v1/search?" +
                 urllib.parse.urlencode({"name": name.split(",")[0].strip(), "count": 5, "language": "en"}))
    found = data.get("results") or []
    if not found:
        raise WebError(f"no place called {name!r} was found")
    hint = name.lower()
    best = next((p for p in found if any(str(p.get(k, "")).lower() in hint for k in ("country", "admin1") if p.get(k))), found[0])
    return best


def open_weather(app, inputs, actor):
    place = _place(_text(inputs, "place"))
    days = max(1, min(int(inputs.get("days") or 3), 7))
    data = _json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto", "forecast_days": days,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code,precipitation",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max"}))
    now, daily = data.get("current") or {}, data.get("daily") or {}
    return {
        "place": ", ".join(str(place[k]) for k in ("name", "admin1", "country") if place.get(k)),
        "now": {"temperature_c": now.get("temperature_2m"), "feels_like_c": now.get("apparent_temperature"),
                "humidity_pct": now.get("relative_humidity_2m"), "wind_kmh": now.get("wind_speed_10m"),
                "sky": WEATHER_CODES.get(now.get("weather_code"), "unknown"), "rain_mm": now.get("precipitation")},
        "days": [{"date": d, "sky": WEATHER_CODES.get(c, "unknown"), "min_c": lo, "max_c": hi, "rain_chance_pct": r, "uv": uv}
                 for d, c, lo, hi, r, uv in zip(daily.get("time", []), daily.get("weather_code", []),
                                                daily.get("temperature_2m_min", []), daily.get("temperature_2m_max", []),
                                                daily.get("precipitation_probability_max", []), daily.get("uv_index_max", []))],
        "source": "Open-Meteo"}


def open_currency(app, inputs, actor):
    base, target = _text(inputs, "from", limit=3).upper(), _text(inputs, "to", limit=40).upper().replace(" ", "")
    amount = float(inputs.get("amount") or 1)
    wanted = [c for c in target.split(",") if c]
    try:
        data = _json("https://api.frankfurter.dev/v1/latest?" + urllib.parse.urlencode({"base": base, "symbols": target}))
    except WebError:
        data = {}
    rates, source = data.get("rates") or {}, "Frankfurter (European Central Bank reference rates)"
    if any(c not in rates for c in wanted):          # ECB has ~30 currencies; ExchangeRate-API has 160 (BDT, ...)
        other = _json(f"https://open.er-api.com/v6/latest/{urllib.parse.quote(base)}")
        extra = {c: other.get("rates", {}).get(c) for c in wanted if c not in rates and other.get("rates", {}).get(c)}
        if extra:
            rates.update(extra)
            source += " and open.er-api.com"
            data.setdefault("date", (other.get("time_last_update_utc") or "")[:16])
    if not rates:
        raise WebError(f"no rate found for {base} to {target}")
    return {"amount": amount, "from": base, "date": data.get("date"),
            "converted": {code: round(rate * amount, 4) for code, rate in rates.items()},
            "rate": rates, "source": source}


def open_holidays(app, inputs, actor):
    country = (_text(inputs, "country", required=False, limit=2) or "AU").upper()
    year = int(inputs.get("year") or __import__("datetime").date.today().year)
    region = _text(inputs, "state", required=False, limit=10).upper()
    data = _json(f"https://date.nager.at/api/v3/PublicHolidays/{year}/{urllib.parse.quote(country)}")
    items = [{"date": h["date"], "name": h.get("localName") or h.get("name"),
              "where": "national" if not h.get("counties") else ", ".join(c.split("-")[-1] for c in h["counties"])}
             for h in data if not region or not h.get("counties") or f"{country}-{region}" in h["counties"]]
    return {"country": country, "year": year, "state": region or None, "holidays": items, "source": "Nager.Date"}


def open_vin(app, inputs, actor):
    vin = re.sub(r"[^A-Za-z0-9]", "", str(inputs.get("vin", ""))).upper()
    if not 11 <= len(vin) <= 17:
        raise ValidationError("a VIN has 17 letters and numbers")
    data = _json(f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json")
    row = (data.get("Results") or [{}])[0]
    keep = ("Make", "Model", "ModelYear", "Trim", "Series", "BodyClass", "DriveType", "FuelTypePrimary",
            "EngineCylinders", "DisplacementL", "EngineModel", "TransmissionStyle", "Doors", "PlantCountry",
            "Manufacturer", "VehicleType", "ElectrificationLevel", "ErrorText")
    return {"vin": vin, **{k: row.get(k) for k in keep if row.get(k)},
            "note": "NHTSA's database is strongest for vehicles sold in North America; Japanese imports may decode only partly.",
            "source": "NHTSA vPIC"}


def open_define(app, inputs, actor):
    word = _text(inputs, "word", limit=60)
    data = _json(f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}")
    if not isinstance(data, list):
        raise WebError(f"no dictionary entry for {word!r}")
    entry = data[0]
    meanings = [{"part_of_speech": m.get("partOfSpeech"),
                 "definitions": [{"meaning": d.get("definition"), "example": d.get("example")} for d in m.get("definitions", [])[:3]],
                 "synonyms": m.get("synonyms", [])[:6]} for m in entry.get("meanings", [])[:4]]
    return {"word": entry.get("word", word), "phonetic": entry.get("phonetic"), "meanings": meanings,
            "source": "Free Dictionary API"}


def open_news(app, inputs, actor):
    topic = _text(inputs, "topic", limit=200)
    limit = max(1, min(int(inputs.get("limit") or 6), 15))
    body, _, _ = _get("https://news.google.com/rss/search?" +
                      urllib.parse.urlencode({"q": topic, "hl": "en-AU", "gl": "AU", "ceid": "AU:en"}))
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise WebError("the news feed could not be read") from exc
    items = [{"title": (i.findtext("title") or "").strip(), "url": (i.findtext("link") or "").strip(),
              "published": i.findtext("pubDate"), "outlet": i.findtext("source")} for i in root.iter("item")]
    return {"topic": topic, "headlines": items[:limit], "source": "Google News"}


def register_opendata(registry: ToolRegistry) -> None:
    def add(name, description, handler, inputs):
        registry.register(Tool(name, description, ActionCategory.WEB_READ, handler, inputs))
    add("open.weather", "Weather now and the forecast for the next days anywhere (Open-Meteo, free).", open_weather,
        {"place": {"type": "string", "description": "Town or city, e.g. 'Perth, Australia'.", "required": True},
         "days": {"type": "integer", "description": "Days of forecast, 1 to 7."}})
    add("open.currency", "Convert money between currencies at today's reference rates (Frankfurter, free).", open_currency,
        {"from": {"type": "string", "description": "Currency code to convert from, e.g. AUD.", "required": True},
         "to": {"type": "string", "description": "Code or comma-separated codes, e.g. USD or USD,JPY.", "required": True},
         "amount": {"type": "number", "description": "How much (default 1)."}})
    add("open.holidays", "Public holidays for a country and year, optionally one state (Nager.Date, free).", open_holidays,
        {"country": {"type": "string", "description": "Two-letter country code (default AU)."},
         "year": {"type": "integer", "description": "Year (default this year)."},
         "state": {"type": "string", "description": "State code, e.g. WA."}})
    add("open.vin", "Decode a vehicle VIN: make, model, year, body, engine, drive (NHTSA, free).", open_vin,
        {"vin": {"type": "string", "description": "The vehicle identification number.", "required": True}})
    add("open.define", "Dictionary: meanings, examples and synonyms of an English word (free).", open_define,
        {"word": {"type": "string", "description": "The word.", "required": True}})
    add("open.news", "Latest news headlines on any topic, with links (Google News, free).", open_news,
        {"topic": {"type": "string", "description": "What the news should be about.", "required": True},
         "limit": {"type": "integer", "description": "How many headlines (1 to 15)."}})
