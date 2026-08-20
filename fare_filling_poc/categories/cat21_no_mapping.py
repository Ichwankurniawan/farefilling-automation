from categories.base import CategoryResolver


class Cat21Resolver(CategoryResolver):
    category = "CAT21"
    # DataMapping: "-- no category-specific mapping defined --", CONSTANT,
    # "Common record fields only... The pricebook carries no field-level
    # rule for this category." Same pattern as CAT09/13/18. The template
    # DOES have real category-specific columns for this block (verified
    # directly), they just have no data source to populate them from.
    has_mapping = False
    output_fields = []
