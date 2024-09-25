from typing import Optional

from pydantic import BaseModel


# TODO: probably make a data file or package and put this in there with quotes
class OptionSymbols(BaseModel):
    # This is randomly camel case
    rootSymbol: str
    options: list[str]


class GetOptionSymbolsResponse(BaseModel):
    # If the underlying is not found, it's {"symbols": null}
    symbols: Optional[list[OptionSymbols]]
