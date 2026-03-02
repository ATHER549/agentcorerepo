
from __future__ import annotations


class Finish:
    """Sentinel class to indicate graph execution is complete."""
    
    def __bool__(self) -> bool:
        return True

    def __eq__(self, /, other):
        return isinstance(other, Finish)
    
    def __repr__(self) -> str:
        return "Finish()"
