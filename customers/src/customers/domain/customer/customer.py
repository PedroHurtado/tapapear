import uuid
from datetime import date
from common.domain import BaseEntity


class TaxType(BaseEntity):
    def __init__(self, id, description: str):
        super().__init__(id)
        self._description = description

    @property
    def description(self):
        return self._description


class Customer(BaseEntity):
    def __init__(
        self,
        id: uuid,
        name: str,
        country: str,
        address: str,
        card: str,
        expirtion_card: date,
        cvc: int,
        tax_type: TaxType,
        tax_number: str,
    ):
        super().__init__(id)
        self._name = name
        self._country = country
        self._address = address
        self._card = card
        self._expiration_card = expirtion_card
        self._cvc = cvc
        self._tax_type = tax_type
        self._tax_numbrer = tax_number

    def update_credit_card(self, card: str, expiration_card: date, cvc: int) -> None:
        self._card = card
        self._expiration_card = expiration_card
        self._cvc = cvc

    def update_personal_info(
        self, name: str, country: str, address: str, tax_type: TaxType, tax_number: str
    ) -> None:
        self._name = name
        self._country = country
        self._addres = address
        self._tax_type = tax_type
        self._tax_numbrer = tax_number

    @staticmethod
    def create(
        id: uuid,
        name: str,
        country: str,
        address: str,
        card: str,
        expirtion_card: date,
        cvc: int,
        tax_type: TaxType,
        tax_number: str,
    ) -> "Customer":
        return Customer(
            id=id,
            name=name,
            country=country,
            addres=address,
            card=card,
            expirtion_card=expirtion_card,
            cvc=cvc,
            tax_type=tax_type,
            tax_number=tax_number,
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def country(self) -> str:
        return self._country

    @property
    def address(self) -> str:
        return self._addres

    @property
    def card(self) -> str:
        return self._card

    @property
    def expiration_card(self) -> date:
        return self._expiration_card

    @property
    def tax_type(self) -> TaxType:
        return self._tax_type

    @property
    def tax_number(self) -> str:
        return self._tax_numbrer
