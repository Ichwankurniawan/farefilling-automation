from categories.base import CategoryResolver


class Cat13Resolver(CategoryResolver):
    category = "CAT13"
    # Verified directly against the real template: CAT13's block has no
    # extra columns at all beyond the common MARKETS fields -- not even
    # RI/Table/CAT, same pattern as CAT09. Sample Fare Rules condition is
    # exactly "NONE UNLESS OTHERWISE SPECIFIED" (deterministic), so unlike
    # CAT09 there's no free-text narrative needing an AI-derived note --
    # a plain has_mapping=False (common fields only) is the right fit.
    has_mapping = False
    output_fields = []
