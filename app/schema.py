"""SupplierCard — контракт данных поставщика с провенансом по полям."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    url: str
    engine: str
    fetched_at: datetime


class Phone(BaseModel):
    raw: str
    e164: Optional[str] = None  # normalized +7XXXXXXXXXX


class Email(BaseModel):
    address: str


class SupplierCard(BaseModel):
    # identity
    name: str
    inn: Optional[str] = None
    identity_key: str

    # contacts
    phones: List[Phone] = Field(default_factory=list)
    emails: List[Email] = Field(default_factory=list)
    website: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None

    # commercial (TZ item 03)
    min_order: Optional[str] = None
    price_range: Optional[str] = None
    delivery: Optional[str] = None
    certs: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)

    # meta
    sources: List[SourceRef] = Field(default_factory=list)
    confidence: float = 0.0
    extracted_at: datetime = Field(default_factory=datetime.utcnow)

    def completeness(self) -> float:
        """Weighted field completeness, 0..1 — used by scorer and UI."""
        weights = {
            "inn": 3.0, "phones": 3.0, "website": 2.0, "email": 1.5,
            "address": 1.5, "city": 1.0, "min_order": 1.0, "price_range": 1.0,
            "delivery": 1.0, "certs": 1.0,
        }
        total = sum(weights.values())
        filled = 0.0
        if self.inn:
            filled += weights["inn"]
        if self.phones:
            filled += weights["phones"]
        if self.website:
            filled += weights["website"]
        if self.emails:
            filled += weights["email"]
        if self.address:
            filled += weights["address"]
        if self.city:
            filled += weights["city"]
        if self.min_order:
            filled += weights["min_order"]
        if self.price_range:
            filled += weights["price_range"]
        if self.delivery:
            filled += weights["delivery"]
        if self.certs:
            filled += weights["certs"]
        return round(filled / total, 3)


class SearchRequest(BaseModel):
    category: str
    city: str
    force_refresh: bool = False
    ru_only: bool = True  # RF-only sourcing by default; False = include foreign suppliers


class SearchResponse(BaseModel):
    job_id: Optional[str] = None
    cached: bool = False
    suppliers: List[SupplierCard] = Field(default_factory=list)
