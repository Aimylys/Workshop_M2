
from decimal import Decimal

from pydantic import BaseModel, Field, ConfigDict


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    balance: Decimal


class TransactionRequest(BaseModel):
    source_account_id: int
    destination_account_id: int
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_account_id: int
    destination_account_id: int
    amount: Decimal
