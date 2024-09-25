from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Callable, Literal, Optional, Self, Union

from pydantic import (
    AliasPath,
    BaseModel,
    Field,
    TypeAdapter,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic_core.core_schema import SerializerFunctionWrapHandler, ValidationInfo


class OrderStatus(str, Enum):
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    EXPIRED = "expired"
    CANCELED = "canceled"
    PENDING = "pending"
    REJECTED = "rejected"
    ERROR = "error"


# When you submit the order the key for stop price is "stop", but when the order details
# are fetched, it's "stop_price". I bet there's a story there.
def order_type_price_field_match[T: BaseModel](
    stop_price_field_name: Literal["stop", "stop_price"],
) -> Callable[[T], T]:
    def _order_type_price_field_match(model: T) -> T:
        price_fields = {
            "market": set(),
            "limit": {"price"},
            "stop": {stop_price_field_name},
            "stop_limit": {"price", stop_price_field_name},
            "debit": {"price"},
            "credit": {"price"},
            "even": set(),
        }
        require = price_fields[model.type]
        omit = {"price", stop_price_field_name} - require

        for field in require:
            if getattr(model, field) is None:
                raise ValueError(f"{model.type} order should have {field} field")
        for field in omit:
            if getattr(model, field, None) is not None:
                raise ValueError(f"{model.type} order should not have {field} field")

        return model

    return _order_type_price_field_match


class BaseOrderResponse(BaseModel):
    id: int
    symbol: str
    quantity: int
    status: OrderStatus
    duration: Literal["day", "pre", "post", "gtc"]
    price: Decimal = Field(None)
    avg_fill_price: Decimal
    exec_quantity: int
    last_fill_price: Decimal
    last_fill_quantity: int
    remaining_quantity: int
    create_date: datetime
    transaction_date: datetime
    reason_description: str = Field(None)
    tag: str = Field(None, max_length=255, pattern=r"^[a-zA-Z0-9\-]+$")

    _order_type_price_field_match = model_validator(mode="after")(
        order_type_price_field_match("stop_price")
    )


class EquityOrderResponse(BaseOrderResponse):
    type: Literal["market", "limit", "stop", "stop_limit"]
    side: Literal["buy", "buy_to_cover", "sell", "sell_short"]
    klass: Literal["equity"] = Field(..., alias="class")
    stop_price: float = Field(None)


class OptionOrderResponse(BaseOrderResponse):
    type: Literal["market", "limit", "stop", "stop_limit"]
    side: Literal["buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close"]
    klass: Literal["option"] = Field(..., alias="class")
    stop_price: float = Field(None)
    option_symbol: str


class OptionLeg(OptionOrderResponse):
    # Tradier duplicates these on the legs, but they simply match the overall multileg
    # order type.
    type: Literal["market", "debit", "even", "credit"]


class MultilegOrderResponse(BaseOrderResponse):
    """Tradier API response order for a multileg order.

    Note that for the legs, `price` will be the overall price of the entire order,
    identical and duplicated for each leg. The leg prices will appear as avg_fill_price
    (and last_fill_price)."""

    type: Literal["market", "debit", "even", "credit"]
    side: Literal["buy"]  # Multileg orders are always submitted as buy
    klass: Literal["multileg"] = Field(..., alias="class")
    num_legs: int
    strategy: Literal[
        "freeform",
        "covered_call",
        "protective_put",
        "strangle",
        "straddle",
        "spread",
        "collar",
        "butterfly",
        "condor",
        "unknown",
    ]
    leg: list[OptionLeg]

    # Validation done in order of field definition, so to validate the root type
    # matches all legs, validate on legs after it's already been set.
    @field_validator("leg")
    @classmethod
    def cast_orders_to_list(cls, value: list[OptionLeg], info: ValidationInfo) -> Any:
        if not all(leg.type == info.data["type"] for leg in value):
            raise ValueError("each leg type must match root type")
        return value


# TODO: combo (stock plus option) isn't supported
OrderResponse = Annotated[
    Union[
        EquityOrderResponse,
        OptionOrderResponse,
        MultilegOrderResponse,
    ],
    Field(..., discriminator="klass"),
]


class GetOrdersResponse(BaseModel):
    # Orders actually live at orders.order, but because of the complex validation we
    # need , we cannot do AliasPath("orders", "order") or we do not see the value of
    # the root "orders" key and cannot detect if it was the literal string "null".
    orders: list[OrderResponse] = Field(validation_alias=AliasPath("orders"))

    @field_validator("orders", mode="before")
    @classmethod
    def validate_orders(cls, value: Any) -> Any:
        # Tradier uses {"orders": "null"} (literal string null) for no orders.
        if value == "null":
            return []
        # Single orders are {"orders": {"order": { ... }} with a dict
        orders = isinstance(value, dict) and value.get("order")
        if not orders:
            raise ValueError("orders must be a dict containing an 'order' key")
        elif isinstance(orders, dict):
            return [orders]
        else:
            return orders


# Responses to order interactions come in like:
# {
#     "order": {
#         "id": 60276657,
#         "status": "ok"
#     }
# }
class PlaceOrderResponse(BaseModel):
    id: int = Field(validation_alias=AliasPath("order", "id"))
    status: Literal["ok"] = Field(validation_alias=AliasPath("order", "status"))
    partner_id: str = Field(validation_alias=AliasPath("order", "partner_id"))


class CancelOrderResponse(BaseModel):
    id: int = Field(validation_alias=AliasPath("order", "id"))
    status: Literal["ok"] = Field(validation_alias=AliasPath("order", "status"))


class ModifyOrderResponse(BaseModel):
    id: int = Field(validation_alias=AliasPath("order", "id"))
    status: Literal["ok"] = Field(validation_alias=AliasPath("order", "status"))
    partner_id: str = Field(validation_alias=AliasPath("order", "partner_id"))


class BasePlaceOrderRequest(BaseModel):
    symbol: str
    type: Literal["market", "limit", "stop", "stop_limit", "debit", "credit", "even"]
    duration: Literal["day", "pre", "post", "gtc"]
    price: str = Field(None, pattern=r"^-?\d+(?:\.\d{1,2})?$")
    tag: str = Field(None, max_length=255, pattern=r"^[a-zA-Z0-9\-]+$")

    _order_type_price_field_match = model_validator(mode="after")(
        order_type_price_field_match("stop")
    )


class EquityPlaceOrderRequest(BasePlaceOrderRequest):
    type: Literal["market", "limit", "stop", "stop_limit"]
    side: Literal["buy", "buy_to_cover", "sell", "sell_short"]
    klass: Literal["equity"] = Field("equity", alias="class")
    quantity: str = Field(..., pattern=r"^\d+$")
    stop: str = Field(None, pattern=r"^\d+(?:\.\d{1,2})?$")


class OptionPlaceOrderRequest(BasePlaceOrderRequest):
    type: Literal["market", "limit", "stop", "stop_limit"]
    side: Literal["buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close"]
    klass: Literal["option"] = Field("option", alias="class")
    quantity: str = Field(..., pattern=r"^\d+$")
    option_symbol: str
    stop: str = Field(None, pattern=r"^\d+(?:\.\d{1,2})?$")


class PlaceMultilegOrderLeg(BaseModel):
    option_symbol: str
    side: Literal["buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close"]
    quantity: str = Field(..., pattern=r"^\d+$")


class MultilegPlaceOrderRequest(BasePlaceOrderRequest):
    type: Literal["market", "debit", "even", "credit"]
    klass: Literal["multileg"] = Field("multileg", alias="class")
    leg_0: PlaceMultilegOrderLeg
    leg_1: PlaceMultilegOrderLeg
    leg_2: Optional[PlaceMultilegOrderLeg] = Field(None)
    leg_3: Optional[PlaceMultilegOrderLeg] = Field(None)

    @model_validator(mode="before")
    @classmethod
    def gather_legs(cls, value: Self) -> Self:
        no_leg_at_last_idx = False
        for i in range(0, 4):
            leg = {
                f"{k}": value.get(f"{k}[{i}]")
                for k in ("option_symbol", "side", "quantity")
                if f"{k}[{i}]" in value
            }
            if len(leg) == 0:
                no_leg_at_last_idx = True
                continue
            elif len(leg) == 3:
                if no_leg_at_last_idx:
                    raise ValueError(f"gap in leg indicies (missing index {i - 1})")
                value[f"leg_{i}"] = leg
            else:
                raise ValueError(f"leg {i} missing value(s)")
        return value

    # Mode must be "always" (the default) not just "json" because we want .model_dump()
    # to dump to the expected flattened Python data (option_symbol[0]: ...) so we can
    # feed it to httpx.put(data={...})
    @model_serializer(mode="wrap")
    def ser_model(self, fn: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = fn(self)
        for i in range(0, 4):
            if (leg := data.pop(f"leg_{i}", None)) is not None:
                data.update({f"{k}[{i}]": v for k, v in leg.items()})
        # Not sure why but you cannot force a field to be dumped by alias and instead
        # must do by_alias=True in the dump call, so we'll just rename here.
        data["class"] = data.pop("klass", "multileg")
        for exclude_if_unset in ("leg_2", "leg_3", "tag"):
            if exclude_if_unset in data and data.get(exclude_if_unset) is None:
                del data[exclude_if_unset]

        return data


PlaceOrderRequest = Annotated[
    Union[
        EquityPlaceOrderRequest,
        OptionPlaceOrderRequest,
        MultilegPlaceOrderRequest,
    ],
    Field(..., discriminator="klass"),
]

TradierRequestPlaceOrderTypeAdapter = TypeAdapter(PlaceOrderRequest)


class ModifyOrderRequest(BaseModel):
    order_id: str
    type: Optional[
        Literal["market", "limit", "stop", "stop_limit", "debit", "credit", "even"]
    ] = Field(None)
    duration: Optional[Literal["day", "pre", "post", "gtc"]] = Field(None)
    price: Optional[str] = Field(None, pattern=r"^-?\d+(?:\.\d{1,2})?$")
    stop: Optional[str] = Field(None, pattern=r"^\d+(?:\.\d{1,2})?$")


class CancelOrderRequest(BaseModel):
    order_id: str
