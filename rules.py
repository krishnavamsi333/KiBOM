"""
rules.py — QA field requirements per component type.

Each list entry is a field name that analyze_bom() will check.
An empty list means "no mandatory fields" for that type.
"""

RULES: dict[str, list[str]] = {
    "resistor":   ["tolerance", "power"],
    "capacitor":  ["voltage"],
    "inductor":   ["power"],
    "led":        ["color"],
    "diode":      ["mpn", "voltage"],
    "transistor": ["mpn"],
    "fuse":       [],       # current rating lives in the value field already
    "connector":  [],       # often generic; MPN not required
    "ic":         ["mpn"],
}