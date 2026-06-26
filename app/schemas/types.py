"""Shared field types for the API schemas."""

from decimal import Decimal
from typing import Annotated

from pydantic import Field

# Money is stored as a 4-decimal value; the example keeps Swagger from
# rendering an absurd auto-generated number for the Decimal field.
Money = Annotated[Decimal, Field(examples=["12.99"])]
