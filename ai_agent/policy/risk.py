from enum import IntEnum


class RiskLevel(IntEnum):
    READ_ONLY = 1
    REVERSIBLE = 2
    DESTRUCTIVE = 3
    FORBIDDEN = 4

    @classmethod
    def max(cls, *levels: "RiskLevel") -> "RiskLevel":
        return max(levels, key=lambda level: level.value)

    def label(self) -> str:
        return self.name
