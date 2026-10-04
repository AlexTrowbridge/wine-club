import pytest

from club.naming import parse_wine_name


@pytest.mark.parametrize(
    "name, producer, vintage, cuvee, varietals, style",
    [
        (
            "Henschke 2020 Henry's Seven Shiraz Grenache Mataro Viognier",
            "Henschke",
            2020,
            "Henry's Seven",
            ["Shiraz", "Grenache", "Mourvèdre", "Viognier"],
            "",
        ),
        (
            "Paul Jaboulet Aine Parallel 45 2020 Cotes du Rhone GSM Carignan Cinsault",
            "Paul Jaboulet Aine Parallel 45",
            2020,
            "Cotes du Rhone",
            ["Grenache", "Shiraz", "Mourvèdre", "Carignan", "Cinsault"],
            "",
        ),
        (
            "Bollinger NV Special Cuvée Champagne Pinot Noir Chardonnay Pinot Meunier",
            "Bollinger",
            None,
            "Special Cuvée Champagne",
            ["Pinot Noir", "Chardonnay", "Pinot Meunier"],
            "sparkling",
        ),
        (
            "Skillogalee 2017 The Cabernets Cabernet Sauvignon Cabernet Franc Malbec",
            "Skillogalee",
            2017,
            "The Cabernets",
            ["Cabernet Sauvignon", "Cabernet Franc", "Malbec"],
            "",
        ),
        (
            # "Montepulciano" here is a place, not the grape.
            "Carpineto 2020 Vino Nobile di Montepulciano Riserva Sangiovese Canaiolo",
            "Carpineto",
            2020,
            "Vino Nobile di Montepulciano Riserva",
            ["Sangiovese", "Canaiolo"],
            "",
        ),
        (
            "Turkey Flat Vineyards 2023 Grenache Rosé",
            "Turkey Flat Vineyards",
            2023,
            "",
            ["Grenache"],
            "rose",
        ),
        (
            "19 Crimes NV Cali by Snoop Smooth Red Blend",
            "19 Crimes",
            None,
            "Cali by Snoop Smooth Red Blend",
            [],
            "",
        ),
        (
            "S.C. Pannell 2020 Basso Garnacha",
            "S.C. Pannell",
            2020,
            "Basso",
            ["Grenache"],
            "",
        ),
    ],
)
def test_parse_wine_name(name, producer, vintage, cuvee, varietals, style):
    p = parse_wine_name(name)
    assert (p.producer, p.vintage, p.cuvee, p.varietals, p.style) == (
        producer,
        vintage,
        cuvee,
        varietals,
        style,
    )


def test_unrecognised_names_are_flagged():
    assert parse_wine_name("19 Crimes NV Cali by Snoop Smooth Red Blend").problems
    assert parse_wine_name("Mystery Wine").problems == ["no vintage found"]
    assert not parse_wine_name("Pepperjack 2021 Cabernet Sauvignon").problems
