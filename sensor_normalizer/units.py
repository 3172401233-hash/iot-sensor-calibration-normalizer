"""温度单位换算。

基准单位为摄氏度（``celsius``）。组件认识的单位别名如下，
大小写、空格与下划线不敏感。
"""

from __future__ import annotations

from .errors import UnknownUnitError

CELSIUS = "celsius"
FAHRENHEIT = "fahrenheit"
KELVIN = "kelvin"

_ALIASES = {
    "celsius": CELSIUS,
    "c": CELSIUS,
    "°c": CELSIUS,
    "degc": CELSIUS,
    "degreecelsius": CELSIUS,
    "fahrenheit": FAHRENHEIT,
    "f": FAHRENHEIT,
    "°f": FAHRENHEIT,
    "degf": FAHRENHEIT,
    "degreefahrenheit": FAHRENHEIT,
    "kelvin": KELVIN,
    "k": KELVIN,
    "degk": KELVIN,
    "degreekelvin": KELVIN,
}


def canonical_unit(unit: str) -> str:
    """把厂商单位名归一为内部单位标识。"""

    if not isinstance(unit, str):
        raise UnknownUnitError(f"温度单位必须是字符串，实际为 {type(unit)!r}")
    key = unit.strip().lower().replace("_", "").replace(" ", "")
    if key not in _ALIASES:
        raise UnknownUnitError(f"不支持的温度单位: {unit!r}")
    return _ALIASES[key]


def to_celsius(value: float, unit: str) -> float:
    """把给定单位的温度值换算为摄氏度。"""

    base = canonical_unit(unit)
    if base == CELSIUS:
        return float(value)
    if base == FAHRENHEIT:
        return (float(value) - 32.0) * 5.0 / 9.0
    if base == KELVIN:
        return float(value) - 273.15
    raise UnknownUnitError(f"不支持的温度单位: {unit!r}")
