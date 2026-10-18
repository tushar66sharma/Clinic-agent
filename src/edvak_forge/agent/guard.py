"""Deterministic safety guard (see docs/decisions/0004-safety-and-policy-in-code.md).

Runs on every message BEFORE the model. It is a second, independent emergency detector:
a message is treated as an emergency if the guard OR the model says so.

- `emergency` match: escalate immediately, without calling the model at all. An emergency
  never waits on a rate-limited API, and the reply is the fixed safe template.
- `urgent` match: the model still handles the message, but urgency can never end up below
  "urgent" and a clinician is always alerted.

The patterns deliberately over-trigger. A false alarm costs staff a minute; a miss can cost a
life. Known idioms (e.g. "dying to get in") are removed before matching, and every pattern is
covered by tests, including the sample traps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

IDIOMS = [
    r"dying to (get|see|come|book|try|go|meet|start)",
    r"to die for",
    r"killing it",
]

EMERGENCY_PATTERNS: dict[str, str] = {
    "chest_pain": r"\bchest\b.{0,30}\b(pain|pressure|tight\w*|crushing|hurts?|squeez\w*"
                  r"|heavy|heaviness|aching|ache|discomfort)"
                  r"|\b(crushing|severe|sharp)\b.{0,20}\bchest\b"
                  r"|\b(pain|pressure|tightness|heaviness|heavy|squeezing|weight)\b.{0,20}\bchest\b"
                  r"|dolor (de|en el) pecho",
    "breathing": r"can'?t breathe|cannot breathe|can ?not breathe|struggling to breathe|gasping"
                 r"|trouble breathing|hard to breathe|short(ness)? of breath"
                 r"|can'?t (finish|complete|get out) (my |a |full )?sentences?"
                 r"|(lips?|face) (are |is |turning )?(blue|purple|gray|grey)"
                 r"|no (puedo|puede) respirar",
    "stroke": r"face (is )?droop\w*|slurred speech|slurring|one side .{0,20}(weak|numb)"
              r"|can'?t (move|feel) (my|her|his) (arm|leg|face)"
              r"|cara ca[ií]da|no (puedo|puede) hablar( bien)?|boca torcida",
    "unconscious": r"passed out|unconscious|unresponsive|won'?t wake|seizure|fainted|collapsed",
    "severe_bleeding": r"bleeding (a lot|heavily|badly|won'?t stop|that won'?t stop|non.?stop)"
                       r"|(black|dark|tarry|bloody) stools?|blood in (my |the |his |her )?"
                       r"(stool|urine|vomit|poop)|vomiting blood|throwing up blood"
                       r"|coughing (up )?blood",
    "anaphylaxis": r"throat (is )?(closing|swelling|tight)|(tongue|lips?) .{0,12}swell\w*"
                   r"|anaphyla\w*|epi-?pen",
    "self_harm": r"kill (myself|himself|herself)|suicid\w*|end(ing)? (my life|it all)|want to die"
                 r"|take my (own )?life|thinking about (dying|death)|quitarme la vida"
                 r"|better off dead|hurt(ing)? (myself|himself|herself)|overdos\w*"
                 r"|no quiero vivir",
    "explicit_emergency": r"\b911\b|ambulance|emergency room|worst headache of (my|her|his) life",
}

HEAD_INJURY = (r"(hit|bump\w*|bang\w*|struck|hurt) (her|his|my|their|the)? ?head"
               r"|head (injury|trauma)|fell.{0,40}head")
HEAD_DANGER = r"confus\w*|disoriented|unconscious|passed out|vomit\w*|drowsy|not making sense|can'?t wake"

URGENT_PATTERNS: dict[str, str] = {
    "low_mood": r"(feel|feeling|felt|been) (really |so |very |pretty )?(low|down|depressed|hopeless)"
                r"|don'?t see the point|no point (in|to|of) (anything|living|life)|can'?t go on"
                r"|worthless|hopeless",
    "fever": r"(?<!no )(?<!without )(?<!without a )\bfever\b|fiebre",
}

GLUCOSE = re.compile(r"(blood sugar|glucose|sugar|bg|reading)\D{0,25}?(\d{2,3})\b")
HYPO_SYMPTOMS = r"shak\w*|sweat\w*|confus\w*|dizzy|faint|pass(ed)? out"


@dataclass
class GuardResult:
    level: Literal["emergency", "urgent", "none"]
    matches: list[str] = field(default_factory=list)

    @property
    def is_emergency(self) -> bool:
        return self.level == "emergency"


def _clean(text: str) -> str:
    text = text.lower().replace("’", "'")
    for idiom in IDIOMS:
        text = re.sub(idiom, " ", text)
    return text


def assess(body: str) -> GuardResult:
    text = _clean(body)
    emergencies = [name for name, pat in EMERGENCY_PATTERNS.items() if re.search(pat, text)]
    if re.search(HEAD_INJURY, text) and re.search(HEAD_DANGER, text):
        emergencies.append("head_injury_with_red_flags")
    for m in GLUCOSE.finditer(text):
        value = int(m.group(2))
        if value < 55 or (value < 70 and re.search(HYPO_SYMPTOMS, text)):
            emergencies.append("hypoglycaemia")
            break
        if value > 400:
            emergencies.append("hyperglycaemia")
            break
    if emergencies:
        return GuardResult("emergency", emergencies)
    urgent = [name for name, pat in URGENT_PATTERNS.items() if re.search(pat, text)]
    return GuardResult("urgent", urgent) if urgent else GuardResult("none")


# ---------------------------------------------------------------- manipulation attempts

INJECTION_PATTERNS = [
    r"ignore (all |any |your |the |previous |prior )+(rules|instructions|policies|prompts?)",
    r"(system|developer) prompt",
    r"</?\s*system\s*>",
    r"\b(admin|developer|debug|god) mode\b",
    r"\byou are now\b",
    r"\b(disregard|bypass|override|disable)\b.{0,30}\b(rules|policy|policies|instructions|restrictions|safety)\b",
    r"\bsystem override\b",
    r"\b(list|show|give me|send me|print)\b.{0,25}\b(every|all)\b.{0,15}\bpatients?\b",
]


def detect_injection(body: str) -> str | None:
    """Return the matching excerpt if the message tries to instruct or subvert the system."""
    text = body.lower()
    for pat in INJECTION_PATTERNS:
        m = re.search(pat, text)
        if m:
            start = max(0, m.start() - 20)
            return body[start:m.end() + 40].strip()
    return None


# ---------------------------------------------------------------- safe emergency reply

EMERGENCY_TEMPLATES = {
    "English": ("Hi {name}, this may be a medical emergency. Please call 911 now or go to the "
                "nearest emergency department. Our clinical team has been alerted to your message."),
    "Spanish": ("Hola {name}, esto podría ser una emergencia médica. Llame al 911 ahora o vaya a "
                "la sala de emergencias más cercana. Nuestro equipo clínico ha sido alertado de "
                "su mensaje."),
}

SPANISH_WORDS = {
    "hola", "necesito", "por", "favor", "tengo", "tiene", "dolor", "mi", "mis", "mamá", "mama",
    "hijo", "hija", "cita", "gracias", "puedo", "puede", "ayuda", "médico", "medico", "pecho",
    "fiebre", "de", "la", "el", "los", "las", "que", "su", "tu", "para", "una", "un", "con", "es",
    "está", "esta", "más", "mas", "algo", "semana", "próxima", "proxima", "hemos", "sus", "y",
}
ENGLISH_WORDS = {
    "the", "and", "to", "is", "my", "i", "you", "your", "a", "for", "of", "in", "can", "please",
    "have", "need", "with", "this", "that", "we", "it", "on", "be", "at", "are", "will", "has",
}


def detect_language(body: str) -> str:
    """Spanish vs English by counting common words. Used when the model is not consulted
    (emergency fast path) and by the evaluation's reply-language check."""
    words = re.findall(r"[a-záéíóúñü]+", body.lower())
    es = sum(w in SPANISH_WORDS for w in words)
    en = sum(w in ENGLISH_WORDS for w in words)
    return "Spanish" if es >= 2 and es > en else "English"


def emergency_reply(sender_name: str | None, language: str) -> str:
    first = (sender_name or "").split()[0] if sender_name and sender_name.split() else "there"
    template = EMERGENCY_TEMPLATES.get(language, EMERGENCY_TEMPLATES["English"])
    if language not in EMERGENCY_TEMPLATES:
        template = EMERGENCY_TEMPLATES["English"]
    return template.format(name=first)
