"""Curated starter recipes for common SAP business objects."""

from sap_knowledge.recipes.business_partner import BUSINESS_PARTNER

BUILTIN_RECIPES = {
    "business_partner": BUSINESS_PARTNER,
    "sap-business-partner": BUSINESS_PARTNER,
}

__all__ = ["BUILTIN_RECIPES", "BUSINESS_PARTNER"]
