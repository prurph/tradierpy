from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Union, Optional, Any

from pydantic import BaseModel, Field, field_validator, AliasPath


class BaseQuote(BaseModel):
    symbol: str
    description: str
    exch: str
    last: Optional[Decimal]
    change: Optional[Decimal]
    volume: int
    open: Optional[Decimal]
    high: Optional[Decimal]
    low: Optional[Decimal]
    close: Optional[Decimal]
    bid: Optional[Decimal]
    ask: Optional[Decimal]
    change_percentage: Optional[Decimal]
    average_volume: int
    last_volume: int
    trade_date: datetime
    prevclose: Optional[Decimal]
    week_52_high: Decimal
    week_52_low: Decimal
    bidsize: int
    bidexch: Optional[str]
    bid_date: datetime
    asksize: int
    askexch: Optional[str]
    ask_date: datetime


class IndexQuote(BaseQuote):
    type: Literal["index"]
    bidexch: None
    askexch: None
    root_symbols: Optional[str]


class StockQuote(BaseQuote):
    type: Literal["stock"]
    root_symbols: Optional[str]


class Greeks(BaseModel):
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    phi: float
    bid_iv: float
    mid_iv: float
    ask_iv: float
    smv_vol: float
    updated_at: str


class OptionQuote(BaseQuote):
    type: Literal["option"]
    open_interest: int
    contract_size: int
    expiration_date: datetime
    expiration_type: Literal["standard", "quarterlys", "weeklys", "eom"]
    option_type: Literal["put", "call"]
    root_symbol: str
    greeks: Optional[Greeks] = None


Quote = Annotated[
    Union[IndexQuote, StockQuote, OptionQuote],
    Field(..., discriminator="type"),
]


class GetQuotesResponse(BaseModel):
    quotes: list[Quote] = Field(
        validation_alias=AliasPath("quotes", "quote"), default_factory=list
    )
    unmatched_symbols: list[str] = Field(
        validation_alias=AliasPath("quotes", "unmatched_symbols", "symbol"),
        default_factory=list,
    )

    @field_validator("quotes", mode="before")
    @classmethod
    def cast_quotes_to_list(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = [value]
        return value

    @field_validator("unmatched_symbols", mode="before")
    @classmethod
    def cast_unmatched_symbols_to_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = [value]
        return value
