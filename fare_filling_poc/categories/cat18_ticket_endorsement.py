from categories.base import CategoryResolver


class Cat18Resolver(CategoryResolver):
    category = "CAT18"
    # Confirmed at the very start of this project: DataMapping explicitly
    # says "-- no category-specific mapping defined --", sourcing CONSTANT.
    # The Fare Rules text looks rich (branches by booking class F-/A-/.../
    # V-/K-) but none of it is meant to be extracted -- common fields only.
    has_mapping = False
    output_fields = []
