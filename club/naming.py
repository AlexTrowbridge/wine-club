"""Parsing spreadsheet-style wine names into structured fields.

Names in the workbook look like ``<Producer> <Vintage|NV> <Cuvée...> <Varietal...>``,
e.g. ``Henschke 2020 Henry's Seven Shiraz Grenache Mataro Viognier``. The varietals
are a trailing run of grape names; anything between the vintage and that run is the
cuvée/label (which may itself mention grapes or places, e.g. "Montepulciano d'Adelaide"
or "Rosso di Montepulciano", and those are deliberately *not* treated as varietals).
"""

import re
from dataclasses import dataclass, field

# Canonical varietal name -> aliases as they appear in names. Seeded from the
# workbook's Stats sheet varietal list ("A/B" entries become aliases).
VARIETALS: dict[str, list[str]] = {
    "Agiorgitiko": [],
    "Albariño": ["Albarino"],
    "Alicante Bouschet": [],
    "Arneis": [],
    "Bacchus": [],
    "Barbera": [],
    "Bobal": [],
    "Cabernet Franc": [],
    "Cabernet Sauvignon": ["Cabernet"],
    "Canaiolo": [],
    "Carignan": ["Carignano", "Cariñena", "Carinena"],
    "Carménère": ["Carmenere"],
    "Castelão": ["Castelao"],
    "Chambourcin": [],
    "Chardonnay": [],
    "Chenin Blanc": [],
    "Cinsault": ["Cinsaut"],
    "Counoise": [],
    "Dolcetto": [],
    "Durif": ["Petite Syrah", "Petite Sirah"],
    "Fiano": [],
    "Friulano": [],
    "Gamay": [],
    "Garganega": [],
    "Gewürztraminer": ["Gewurztraminer", "Traminer"],
    "Graciano": [],
    "Grenache": ["Garnacha", "Cannonau"],
    "Grüner Veltliner": ["Gruner Veltliner"],
    "Lagrein": [],
    "Malbec": [],
    "Marsanne": [],
    "Mencia": ["Mencía"],
    "Merlot": [],
    "Montepulciano": [],
    "Mourvèdre": ["Mourvedre", "Mataro", "Monastrell"],
    "Muscat Blanc à Petits Grains": [],
    "Muscat of Alexandria": [],
    "Nebbiolo": [],
    "Negroamaro": [],
    "Nero d'Avola": [],
    "Petit Verdot": [],
    "Pecorino": [],
    "Pedro Ximenez": ["Pedro Ximénez"],
    "Pinot Blanc": ["Pinot Bianco"],
    "Pinot Gris": ["Pinot Grigio", "Pinot Gris/Grigio"],
    "Pinot Meunier": ["Meunier"],
    "Pinot Noir": ["Pinot Nero"],
    "Pinotage": [],
    "Primitivo": ["Zinfandel"],
    "Refosco": [],
    "Ribolla Gialla": [],
    "Riesling": [],
    "Roussanne": [],
    "Sagrantino": [],
    "Sangiovese": [],
    "Sauvignon Blanc": [],
    "Semillon": ["Sémillon"],
    "Shiraz": ["Syrah"],
    "Tempranillo": ["Tinta Roriz", "Tinto Fino"],
    "Tinta Barroca": [],
    "Touriga Franca": [],
    "Touriga Nacional": [],
    "Trincadeira": ["Trincadiera"],
    "Verdejo": [],
    "Vermentino": [],
    "Viognier": [],
    "Xinomavro": [],
    "Zibibbo": ["Zibbibo"],
}

# Abbreviations that stand for several varietals at once.
BLEND_ABBREVIATIONS: dict[str, list[str]] = {
    "GSM": ["Grenache", "Shiraz", "Mourvèdre"],
    "SGM": ["Shiraz", "Grenache", "Mourvèdre"],
    "GMS": ["Grenache", "Mourvèdre", "Shiraz"],
}

# Joiners that may appear inside a trailing varietal run ("Shiraz & Cabernet").
_JOINERS = {"&", "and", "/", "-", ","}

# Style words that may trail the varietals ("Grenache Rosé"), with the style they imply.
_STYLE_SUFFIXES = {"rosé": "rose", "rose": "rose", "rosato": "rose", "rosado": "rose", "joven": ""}

_VINTAGE_RE = re.compile(r"(?<!\S)(NV|(?:19|20)\d\d)(?!\S)")


@dataclass
class ParsedName:
    producer: str
    vintage: int | None
    cuvee: str
    varietals: list[str] = field(default_factory=list)
    style: str = ""
    problems: list[str] = field(default_factory=list)


def _lexicon(varietals: dict[str, list[str]]) -> list[tuple[list[str], list[str]]]:
    """(token sequence, canonical varietals) pairs, longest first."""
    entries = []
    for canonical, aliases in varietals.items():
        for spelling in [canonical, *aliases]:
            entries.append((spelling.lower().split(), [canonical]))
    for abbr, expansion in BLEND_ABBREVIATIONS.items():
        entries.append(([abbr.lower()], expansion))
    entries.sort(key=lambda e: len(e[0]), reverse=True)
    return entries


def parse_wine_name(name: str, varietals: dict[str, list[str]] | None = None) -> ParsedName:
    name = " ".join(name.split())
    lexicon = _lexicon(varietals or VARIETALS)

    m = _VINTAGE_RE.search(name)
    if not m:
        return ParsedName(producer=name, vintage=None, cuvee="", problems=["no vintage found"])
    producer = name[: m.start()].strip()
    vintage = None if m.group(1) == "NV" else int(m.group(1))
    tokens = name[m.end() :].split()
    problems = [] if producer else ["no producer before vintage"]

    # Strip trailing style words, then consume varietals from the end backwards.
    style = ""
    end = len(tokens)
    while end > 0 and tokens[end - 1].lower() in _STYLE_SUFFIXES:
        style = style or _STYLE_SUFFIXES[tokens[end - 1].lower()]
        end -= 1
    found: list[list[str]] = []
    while end > 0:
        if tokens[end - 1].lower() in _JOINERS and found:
            end -= 1
            continue
        for seq, canon in lexicon:
            n = len(seq)
            if n <= end and [t.lower() for t in tokens[end - n : end]] == seq:
                found.append(canon)
                end -= n
                break
        else:
            break
    # Leading joiners left over belong to neither part.
    while end > 0 and tokens[end - 1].lower() in _JOINERS:
        end -= 1

    ordered: list[str] = []
    for canon in reversed(found):
        for v in canon:
            if v not in ordered:
                ordered.append(v)
    if not ordered:
        problems.append("no trailing varietal recognised")
        # Keep style words as part of the label when there is nothing to attach them to.
        end, style = len(tokens), ""
    if not style and re.search(
        r"\b(champagne|sparkling|prosecco|cava|cr[ée]mant|pet[- ]nat)\b", name, re.IGNORECASE
    ):
        style = "sparkling"
    return ParsedName(
        producer=producer,
        vintage=vintage,
        cuvee=" ".join(tokens[:end]),
        varietals=ordered,
        style=style,
        problems=problems,
    )
