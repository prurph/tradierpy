from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import AliasPath, BaseModel, Field, PositiveInt, field_validator


class Position(BaseModel):
    cost_basis: Decimal
    date_acquired: datetime
    id: PositiveInt
    quantity: int
    symbol: str


class GetPositionsResponse(BaseModel):
    # Unconfirmed that no positions gives "positions": "null", but assuming it's like
    # the other endpoints.
    positions: list[Position] = Field(validation_alias=AliasPath("positions"))

    @field_validator("positions", mode="before")
    @classmethod
    def validate_positions(cls, value: Any) -> Any:
        if value == "null":
            return []
        positions = isinstance(value, dict) and value.get("position")
        if not positions:
            raise ValueError("positions must be a dict containing a 'position' key")
        elif isinstance(positions, dict):
            return [positions]
        else:
            return positions
