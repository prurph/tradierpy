import os
import webbrowser
from datetime import datetime
from json import JSONDecodeError
from typing import Any, Callable, Optional, Union

from httpx import AsyncClient, Response, URL
from pydantic import (
    AliasPath,
    BaseModel,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from tradierpy.account import GetPositionsResponse
from tradierpy.order import (
    CancelOrderRequest,
    ModifyOrderRequest,
    PlaceOrderRequest,
    CancelOrderResponse,
    GetOrdersResponse,
    ModifyOrderResponse,
    PlaceOrderResponse,
)
from tradierpy.quote import GetQuotesResponse


class DownstreamErrorResponse(BaseModel):
    """Returned with logical(?) issues with Tradier, like insufficient margin.

    Attached to a 200 response; should probably have been a 422.
    https://documentation.tradier.com/brokerage-api/overview/errors

    Sample:

    {
        "errors": {
            "error": [
                "Backoffice rejected override of the order.",
                "UnexpectedBuyToCoverOrder",
            ]
        }
    }
    """

    # I'm assuming this is going to be a string if there's ever only one
    errors: list[str] = Field(validation_alias=AliasPath("errors"))

    @field_validator("errors", mode="before")
    @classmethod
    def validate_orders(cls, value: Any) -> Any:
        if value == "null":
            return []
        # Single orders are {"orders": {"order": { ... }} with a dict
        errors = isinstance(value, dict) and value.get("error")
        if not errors:
            raise ValueError("expecting errors dict with error key")
        elif isinstance(errors, str):
            return [errors]
        else:
            return errors


class ClientErrorResponse(BaseModel):
    """Returned with 4xx requests (we did something wrong)."""

    code: int
    message: str


class OrderAlreadyFinalized(BaseModel):
    """Returned when an order could not be canceled or modified because it's already in
    a finalized state.

    Tradier returns 400's if try to modify/cancel an already finalized order, and
    instead of JSON it's just a text response. Woof."""

    message: str


"""The errors that are encoded as JSON."""
JsonErrorResponse = Union[DownstreamErrorResponse, ClientErrorResponse]


class ClientTradier:
    def __init__(self, account_id=None, access_token=None):
        self.account_id = account_id or os.getenv("TRADIER_ACCOUNT_ID")
        self.__access_token = access_token or os.getenv("TRADIER_ACCESS_TOKEN")

        if self.account_id is None:
            raise ValueError("missing TRADIER_ACCOUNT_ID in env")
        if self.__access_token is None:
            raise ValueError("missing TRADIER_ACCESS_TOKEN in env")

        self.__headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.__access_token}",
        }
        self.base_url = "https://api.tradier.com/v1"
        self.try_parse_positions_response = ClientTradier.validate_json_response(
            GetPositionsResponse
        )
        self.try_parse_orders_response = ClientTradier.validate_json_response(
            GetOrdersResponse
        )
        self.try_parse_quotes_response = ClientTradier.validate_json_response(
            GetQuotesResponse
        )
        self.try_parse_place_order_response = ClientTradier.validate_json_response(
            PlaceOrderResponse
        )
        self.try_parse_modify_order_response = ClientTradier.validate_json_response(
            ModifyOrderResponse
        )
        self.try_parse_cancel_order_response = ClientTradier.validate_json_response(
            CancelOrderResponse
        )

    async def get_positions(self) -> GetPositionsResponse:
        async with AsyncClient() as client:
            res = await client.get(
                f"{self.base_url}/accounts/{self.account_id}/positions",
                headers=self.__headers,
            )

            return self.try_parse_positions_response(res)

    async def get_quotes(self, *symbols: str) -> GetQuotesResponse:
        async with AsyncClient() as client:
            res = await client.post(
                f"{self.base_url}/markets/quotes",
                headers=self.__headers,
                data={"symbols": ",".join(symbols)},
            )

            return self.try_parse_quotes_response(res)

    async def get_orders(self, since: Optional[datetime] = None) -> GetOrdersResponse:
        # "Hidden" filtered api: https://documentation.tradier.com/brokerage-api/accounts/get-account-orders-filtered
        params = {"includeTags": "true"}
        if since is not None:
            params["start"] = since.strftime("%Y-%m-%d")
            params["limit"] = 10000
            params["filter"] = "all"
        async with AsyncClient() as client:
            res = await client.get(
                f"{self.base_url}/accounts/{self.account_id}/orders",
                headers=self.__headers,
                params=params,
            )

            return self.try_parse_orders_response(res)

    async def get_order(self, order_id: int) -> GetOrdersResponse:
        async with AsyncClient() as client:
            res = await client.get(
                f"{self.base_url}/accounts/{self.account_id}/orders/{order_id}",
                headers=self.__headers,
                params={"includeTags": "true"},
            )

            return self.try_parse_orders_response(res)

    async def place_order(self, order: PlaceOrderRequest) -> PlaceOrderResponse:
        async with AsyncClient() as client:
            res = await client.post(
                f"{self.base_url}/accounts/{self.account_id}/orders",
                headers=self.__headers,
                data=order.model_dump(),
            )

            return self.try_parse_place_order_response(res)

    async def stage_order(self, order: PlaceOrderRequest) -> bool:
        return webbrowser.open(
            str(URL("https://dash.tradier.com/tradelink", params=order.model_dump()))
        )

    async def modify_order(
        self, order: ModifyOrderRequest
    ) -> Union[ModifyOrderResponse, OrderAlreadyFinalized]:
        async with AsyncClient() as client:
            res = await client.put(
                f"{self.base_url}/accounts/{self.account_id}/orders/{order.order_id}",
                headers=self.__headers,
                data=order.model_dump(),
            )

            # Maybe shouldn't be returning an "error" here but throwing if we can't
            # validate the JSON? Counter-argument is this state is something the client
            # likely wants to handle as unexceptional (I tried to modify, but it was
            # already filled or canceled).
            if res.status_code == 400:
                return OrderAlreadyFinalized(message=res.text)

            return self.try_parse_modify_order_response(res)

    async def cancel_order(
        self, order: CancelOrderRequest
    ) -> Union[CancelOrderResponse, OrderAlreadyFinalized]:
        async with AsyncClient() as client:
            res = await client.delete(
                f"{self.base_url}/accounts/{self.account_id}/orders/{order.order_id}",
                headers=self.__headers,
            )

            # Maybe shouldn't be returning an "error" here but throwing if we can't
            # validate the JSON? Counter-argument is this state is something the client
            # likely wants to handle as unexceptional (I tried to cancel, but it was
            # already filled).
            if res.status_code == 400:
                return OrderAlreadyFinalized(message=res.text)

            return self.try_parse_cancel_order_response(res)

    # Could maybe just make this an Either instead of throwing a value error of the
    # Tradier error
    @staticmethod
    def validate_json_response[T: BaseModel](
        concrete_type: type[T],
    ) -> Callable[[Response], T]:
        ta = TypeAdapter(Union[JsonErrorResponse, concrete_type])

        def f(res: Response) -> T:
            try:
                # Could also do this as ta.validate_json(res.content)
                # This would cause Pydantic to raise a ValidationError on the invalid
                # JSON. I'm thinking it's preferable to leave that to the response class
                # then validate what we know is a decoded Python structure.
                if isinstance(
                    err_or_t := ta.validate_python(res.json()), JsonErrorResponse
                ):
                    raise ValueError(err_or_t)
                else:
                    return err_or_t

            except JSONDecodeError as e:
                raise ValueError(f"failed to decode response as json {res}") from e
            except ValidationError as e:
                raise ValueError(f"failed to validate json as {ta._type} {res.json()}")

        return f
